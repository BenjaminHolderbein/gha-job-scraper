"""Live tests — hit real upstream APIs and verify each source still works.

Excluded from default test runs (see pyproject.toml ``addopts``). Run with::

    uv run pytest -m live

Each test asserts:
  1. The fetcher returns at least one job.
  2. Every returned job conforms to the normalized schema.
  3. The company tag is what we expect (catches accidental routing bugs).

These tests intentionally do not assert on counts/content — only that the
upstream API is reachable and our normalization still produces well-formed
records. They are designed to fail loudly when an API breaks or changes shape.
"""

from __future__ import annotations

import pytest

from scraper import sources

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


def _assert_well_formed(jobs: list[dict], expected_company: str, id_prefix: str) -> None:
    assert isinstance(jobs, list)
    assert len(jobs) > 0, f"{expected_company}: zero jobs returned"
    for job in jobs:
        assert set(job.keys()) == REQUIRED_KEYS, f"{expected_company}: bad keys {job.keys()}"
        assert job["company"] == expected_company
        assert job["id"].startswith(id_prefix)
        assert isinstance(job["title"], str)
        assert isinstance(job["remote"], bool)
        assert isinstance(job["url"], str)


@pytest.mark.live
def test_handshake_live():
    _assert_well_formed(sources.fetch_handshake(), "Handshake", "handshake:")


@pytest.mark.live
def test_zoox_live():
    _assert_well_formed(sources.fetch_zoox(), "Zoox", "zoox:")


@pytest.mark.live
def test_aws_live():
    _assert_well_formed(sources.fetch_aws(), "AWS", "aws:")


@pytest.mark.live
def test_uber_live():
    _assert_well_formed(sources.fetch_uber(), "Uber", "uber:")


@pytest.mark.live
def test_zap_surgical_live():
    # Zap currently posts zero roles publicly — assert the call succeeds and
    # the result is a (possibly empty) list of well-formed records.
    jobs = sources.fetch_zap_surgical()
    assert isinstance(jobs, list)
    for job in jobs:
        assert set(job.keys()) == REQUIRED_KEYS
        assert job["company"] == "Zap Surgical"


@pytest.mark.live
def test_google_live():
    # Google requires Playwright; if Playwright isn't installed in the test
    # env the fetcher returns []. Treat empty as a skip rather than fail.
    jobs = sources.fetch_google()
    if not jobs:
        pytest.skip("google: empty result (Playwright missing or zero matches)")
    # The Google careers board is shared across Alphabet subsidiaries
    # (YouTube, DeepMind, Verily, ...), so company can be any of those —
    # only enforce schema + id-prefix here.
    for job in jobs:
        assert set(job.keys()) == REQUIRED_KEYS
        assert job["id"].startswith("google:")
        assert job["company"]
