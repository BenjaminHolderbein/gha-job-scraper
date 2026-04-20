"""Tests for scraper.sources — offline, no network calls."""

from __future__ import annotations

import json
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


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        return None


class _FakeSession:
    """Minimal stand-in for requests.Session that returns canned JSON per URL."""

    def __init__(self, url_to_data: dict):
        self._url_to_data = url_to_data
        self.calls: list[str] = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        if url not in self._url_to_data:
            raise AssertionError(f"unexpected URL: {url}")
        data = self._url_to_data[url]
        if isinstance(data, Exception):
            raise data
        return _FakeResponse(data)


def _load_fixture(name: str):
    with (FIXTURES / name).open() as f:
        return json.load(f)


def test_ashby_normalizes_fixture():
    payload = _load_fixture("ashby_sample.json")
    session = _FakeSession({sources.HANDSHAKE_URL: payload})

    jobs = sources.fetch_handshake(session=session)

    assert session.calls == [sources.HANDSHAKE_URL]
    assert len(jobs) == len(payload["jobs"])
    for job in jobs:
        assert set(job.keys()) == REQUIRED_KEYS
        assert job["company"] == "Handshake"
        assert job["id"].startswith("handshake:")

    # Map back to source records to verify isRemote -> remote per-record.
    by_id = {j["id"]: j for j in jobs}
    for raw in payload["jobs"]:
        normalized = by_id[f"handshake:{raw['id']}"]
        assert normalized["remote"] is bool(raw.get("isRemote", False))
        # url prefers jobUrl over applyUrl
        assert normalized["url"] == (raw.get("jobUrl") or raw.get("applyUrl") or "")
        assert normalized["posted_at"] == raw.get("publishedAt", "")

    # Fixture was constructed with exactly one remote and one onsite entry.
    remote_flags = sorted(j["remote"] for j in jobs)
    assert remote_flags == [False, True]


def test_lever_normalizes_fixture():
    payload = _load_fixture("lever_sample.json")
    session = _FakeSession({sources.ZOOX_URL: payload})

    jobs = sources.fetch_zoox(session=session)

    assert session.calls == [sources.ZOOX_URL]
    assert len(jobs) == len(payload)
    for job in jobs:
        assert set(job.keys()) == REQUIRED_KEYS
        assert job["company"] == "Zoox"
        assert job["id"].startswith("zoox:")
        # posted_at must be an ISO8601 UTC string
        assert job["posted_at"].endswith("+00:00")

    # remote flag is True iff workplaceType == "remote" (spec), False for
    # hybrid/onsite/anything else.
    by_id = {j["id"]: j for j in jobs}
    for raw in payload:
        normalized = by_id[f"zoox:{raw['id']}"]
        assert normalized["remote"] is (raw.get("workplaceType") == "remote")
        assert normalized["title"] == raw.get("text", "")
        assert normalized["location"] == raw["categories"].get("location", "")
        assert normalized["department"] == raw["categories"].get("department", "")
        assert normalized["url"] == raw.get("hostedUrl", "")

    # Verify the ms-epoch -> ISO string conversion against a known value.
    # Pick the first raw job and recompute expected.
    from datetime import datetime, timezone

    raw0 = payload[0]
    expected = datetime.fromtimestamp(
        raw0["createdAt"] / 1000, tz=timezone.utc
    ).isoformat()
    assert by_id[f"zoox:{raw0['id']}"]["posted_at"] == expected


def test_lever_remote_workplace_type_maps_to_true():
    """Directly cover the workplaceType == 'remote' -> remote=True branch.

    Zoox's live feed has no remote roles today, so the fixture can't exercise
    this branch. Synthesize a minimal Lever-shaped record to cover it.
    """
    fake_payload = [
        {
            "id": "xyz",
            "text": "Remote ML Engineer",
            "categories": {"department": "ML", "location": "Remote"},
            "workplaceType": "remote",
            "hostedUrl": "https://jobs.lever.co/zoox/xyz",
            "createdAt": 1700000000000,
        }
    ]
    session = _FakeSession({sources.ZOOX_URL: fake_payload})
    jobs = sources.fetch_zoox(session=session)
    assert len(jobs) == 1
    assert jobs[0]["remote"] is True
    assert jobs[0]["id"] == "zoox:xyz"


def test_fetch_all_continues_on_source_failure(monkeypatch):
    """If one source raises, the other's jobs are still returned."""
    sentinel_jobs = [
        {
            "id": "zoox:ok",
            "company": "Zoox",
            "title": "t",
            "department": "",
            "location": "",
            "remote": False,
            "url": "",
            "posted_at": "",
        }
    ]

    def boom(session=None):
        raise RuntimeError("handshake down")

    def ok(session=None):
        return list(sentinel_jobs)

    monkeypatch.setattr(sources, "fetch_handshake", boom)
    monkeypatch.setattr(sources, "fetch_zoox", ok)

    result = sources.fetch_all()
    assert result == sentinel_jobs


def test_fetch_all_both_sources_succeed(monkeypatch):
    monkeypatch.setattr(sources, "fetch_handshake", lambda session=None: [{"id": "handshake:a"}])
    monkeypatch.setattr(sources, "fetch_zoox", lambda session=None: [{"id": "zoox:b"}])
    result = sources.fetch_all()
    assert [j["id"] for j in result] == ["handshake:a", "zoox:b"]


def test_fetch_handshake_raises_on_http_error():
    """HTTP errors propagate (raise_for_status)."""

    class _ErrResponse:
        def raise_for_status(self):
            raise RuntimeError("500")

        def json(self):  # pragma: no cover
            return {}

    class _ErrSession:
        def get(self, url, timeout=None):
            return _ErrResponse()

    with pytest.raises(RuntimeError):
        sources.fetch_handshake(session=_ErrSession())
