"""Tests for scraper.sources.fetch_google — offline, no browser launched.

Playwright is hard to unit-test end-to-end, so the strategy here is:
  1. Unit-test the pure ``_parse_google_job_card`` helper with synthetic cards.
  2. Replace ``playwright.sync_api.sync_playwright`` with a fake for the full
     ``fetch_google`` function, so we exercise the control flow without
     spawning a real browser.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from scraper import sources

FIXTURES = Path(__file__).parent / "fixtures"
REQUIRED_KEYS = {
    "id",
    "company",
    "title",
    "department",
    "location",
    "remote",
    "url",
    "posted_at",
}


def _load_fixture(name: str):
    with (FIXTURES / name).open() as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# _parse_google_job_card — pure function, tests the contract.
# ---------------------------------------------------------------------------


def test_parse_google_job_card_fixture_shape():
    cards = _load_fixture("google_sample.json")
    jobs = [sources._parse_google_job_card(c) for c in cards]
    jobs = [j for j in jobs if j is not None]
    assert len(jobs) == len(cards)
    for job in jobs:
        assert set(job.keys()) == REQUIRED_KEYS
        assert job["id"].startswith("google:")
        assert job["remote"] is False
        assert job["posted_at"] == ""
        assert job["url"].startswith(
            "https://www.google.com/about/careers/applications/jobs/results/"
        )
        # No doubled "jobs/results/" segment in the URL.
        assert job["url"].count("jobs/results/") == 1

    # Multiple locations are joined with "; ".
    multi = next(j for j in jobs if "Sunnyvale" in j["location"])
    assert "Sunnyvale, CA, USA" in multi["location"]
    assert "Kirkland, WA, USA" in multi["location"]
    assert "; " in multi["location"]

    # Default company is "Google" when scraper saw it.
    assert all(j["company"] == "Google" for j in jobs)

    # ID extraction: digits before the first "-".
    first = jobs[0]
    assert first["id"] == "google:130633982545928902"


def test_parse_google_job_card_missing_fields_returns_none():
    assert sources._parse_google_job_card({}) is None
    assert (
        sources._parse_google_job_card({"title": "", "href": "jobs/results/123-x"})
        is None
    )
    assert (
        sources._parse_google_job_card({"title": "ML Eng", "href": ""}) is None
    )
    # Non-matching href (no numeric id) → None.
    assert (
        sources._parse_google_job_card(
            {"title": "ML Eng", "href": "jobs/results/not-an-id"}
        )
        is None
    )


def test_parse_google_job_card_absolute_href_preserved():
    job = sources._parse_google_job_card(
        {
            "title": "t",
            "company": "Google",
            "locations": ["Mountain View, CA, USA"],
            "href": "https://www.google.com/about/careers/applications/jobs/results/42-t",
        }
    )
    assert job is not None
    assert job["url"] == (
        "https://www.google.com/about/careers/applications/jobs/results/42-t"
    )
    assert job["id"] == "google:42"


def test_parse_google_job_card_empty_company_defaults_to_google():
    job = sources._parse_google_job_card(
        {
            "title": "t",
            "company": "",
            "locations": [],
            "href": "jobs/results/42-t",
        }
    )
    assert job is not None
    assert job["company"] == "Google"
    assert job["location"] == ""


# ---------------------------------------------------------------------------
# fetch_google — full-function tests with fake playwright.
# ---------------------------------------------------------------------------


class _FakePage:
    """Minimal page that returns one canned card list on first navigation,
    then empty lists (simulating "no more results → stop paginating")."""

    def __init__(self, cards_per_url):
        self._cards_per_url = cards_per_url
        self._current_url = None

    def set_default_timeout(self, ms):
        pass

    def goto(self, url, timeout=None, wait_until=None):
        self._current_url = url

    def wait_for_selector(self, selector, timeout=None):
        return None

    def evaluate(self, js):
        return self._cards_per_url.get(self._current_url, [])


class _FakeContext:
    def __init__(self, page):
        self._page = page

    def new_page(self):
        return self._page


class _FakeBrowser:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_context(self, **kwargs):
        return _FakeContext(self._page)

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser):
        self._browser = browser

    def launch(self, **kwargs):
        return self._browser


class _FakePW:
    def __init__(self, browser):
        self.chromium = _FakeChromium(browser)


class _FakeSyncPlaywrightCM:
    def __init__(self, browser):
        self._browser = browser

    def __enter__(self):
        return _FakePW(self._browser)

    def __exit__(self, *args):
        return False


def _install_fake_playwright(monkeypatch, sync_playwright_factory):
    """Install a fake ``playwright.sync_api`` module exposing
    ``sync_playwright`` per the supplied factory."""
    fake_pkg = types.ModuleType("playwright")
    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = sync_playwright_factory
    fake_pkg.sync_api = fake_sync_api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", fake_pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)


def test_fetch_google_returns_list(monkeypatch):
    """Happy path: fake playwright returns synthetic cards → normalized jobs."""
    # Only the first (query, location) combo produces cards; everything else
    # returns []. Since _parse expects raw card dicts and the fake page is
    # asked via `evaluate`, we stash them keyed by URL.
    cards = [
        {
            "title": "ML Engineer",
            "company": "Google",
            "locations": ["Mountain View, CA, USA"],
            "href": "jobs/results/111-ml-engineer",
        },
        {
            "title": "Research Scientist",
            "company": "Google",
            "locations": ["Sunnyvale, CA, USA"],
            "href": "jobs/results/222-research-scientist",
        },
    ]
    # Match against whatever URL the first navigate produces — the real code
    # builds it from constants, so we just always return the cards on the
    # first call and [] afterwards.
    calls = {"n": 0}

    class _Page(_FakePage):
        def evaluate(self, js):
            calls["n"] += 1
            return cards if calls["n"] == 1 else []

    page = _Page({})
    browser = _FakeBrowser(page)
    _install_fake_playwright(monkeypatch, lambda: _FakeSyncPlaywrightCM(browser))

    jobs = sources.fetch_google()

    assert isinstance(jobs, list)
    assert len(jobs) == 2
    for job in jobs:
        assert set(job.keys()) == REQUIRED_KEYS
        assert job["id"].startswith("google:")
        assert job["company"] == "Google"
    ids = sorted(j["id"] for j in jobs)
    assert ids == ["google:111", "google:222"]
    assert browser.closed is True


def test_fetch_google_handles_missing_playwright(monkeypatch):
    """If the playwright package import fails, fetch_google returns []."""
    # Clobber the package so `from playwright.sync_api import sync_playwright`
    # raises ImportError inside the function.
    bad_pkg = types.ModuleType("playwright")
    # Do NOT set .sync_api → the submodule import will fail.
    monkeypatch.setitem(sys.modules, "playwright", bad_pkg)
    monkeypatch.delitem(sys.modules, "playwright.sync_api", raising=False)

    # Also ensure the import machinery cannot find a real playwright package
    # on disk (if it's installed locally). We do this by making the finder
    # raise for the submodule.
    import importlib.abc
    import importlib.machinery

    class _BlockSyncApi(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name == "playwright.sync_api":
                raise ImportError("blocked for test")
            return None

    finder = _BlockSyncApi()
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])

    result = sources.fetch_google()
    assert result == []


def test_fetch_google_handles_launch_failure(monkeypatch):
    """If chromium launch raises, fetch_google returns [] (no re-raise)."""

    class _ExplodingChromium:
        def launch(self, **kwargs):
            raise RuntimeError("chromium binary missing")

    class _ExplodingPW:
        chromium = _ExplodingChromium()

    class _ExplodingCM:
        def __enter__(self):
            return _ExplodingPW()

        def __exit__(self, *args):
            return False

    _install_fake_playwright(monkeypatch, lambda: _ExplodingCM())

    result = sources.fetch_google()
    assert result == []


def test_fetch_google_handles_zero_results(monkeypatch):
    """If every (query, location) combo yields zero cards, return []."""
    page = _FakePage({})  # evaluate() always returns [] for unknown URLs
    browser = _FakeBrowser(page)
    _install_fake_playwright(monkeypatch, lambda: _FakeSyncPlaywrightCM(browser))

    result = sources.fetch_google()
    assert result == []
    assert browser.closed is True


def test_fetch_google_dedupes_across_combos(monkeypatch):
    """The same job id surfaced under multiple (query, location) combos is
    returned only once."""
    dup = [
        {
            "title": "ML Engineer",
            "company": "Google",
            "locations": ["Mountain View, CA, USA"],
            "href": "jobs/results/111-ml-engineer",
        }
    ]

    class _Page(_FakePage):
        def __init__(self):
            super().__init__({})
            self.navigations = 0

        def goto(self, url, timeout=None, wait_until=None):
            self.navigations += 1

        def evaluate(self, js):
            # First two navigations return the same single job;
            # subsequent ones are empty (→ stop paginating).
            return dup if self.navigations <= 2 else []

    page = _Page()
    browser = _FakeBrowser(page)
    _install_fake_playwright(monkeypatch, lambda: _FakeSyncPlaywrightCM(browser))

    jobs = sources.fetch_google()
    assert len(jobs) == 1
    assert jobs[0]["id"] == "google:111"
