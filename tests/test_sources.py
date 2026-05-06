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

    def get(self, url, timeout=None, params=None):
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


class _UberFakeSession:
    """Session stand-in for Uber's POST endpoint.

    Returns the same canned payload for every POST regardless of the query
    body (the production code issues one POST per UBER_QUERIES entry — for
    fixture tests we want each call to see the fixture).
    """

    def __init__(self, payload):
        self._payload = payload
        self.calls: list[dict] = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if url != sources.UBER_URL:
            raise AssertionError(f"unexpected URL: {url}")
        return _FakeResponse(self._payload)


def test_uber_normalizes_fixture():
    payload = _load_fixture("uber_sample.json")
    session = _UberFakeSession(payload)

    jobs = sources.fetch_uber(session=session)

    # Uber issues one POST per query; results dedupe across queries by id, so
    # the fixture's 4 unique ids should appear exactly once in the output.
    assert len(jobs) == 4
    assert len(session.calls) == len(sources.UBER_QUERIES)
    for call in session.calls:
        assert call["headers"]["x-csrf-token"]
        assert call["json"]["params"]["page"] == 0
        assert isinstance(call["json"]["params"]["query"], str)

    for job in jobs:
        assert set(job.keys()) == REQUIRED_KEYS
        assert job["company"] == "Uber"
        assert job["id"].startswith("uber:")
        assert job["url"].startswith("https://www.uber.com/global/en/careers/list/")
        assert job["remote"] is False

    by_id = {j["id"]: j for j in jobs}
    # Multi-location US role: "City, Region" join across allLocations.
    sf_role = by_id["uber:158248"]
    assert "San Francisco, California" in sf_role["location"]
    assert "Sunnyvale, California" in sf_role["location"]
    # Non-US role: country name appended so filters can reject foreign locations.
    nl_role = by_id["uber:300002"]
    assert "Netherlands" in nl_role["location"]


def test_uber_dedupes_across_queries():
    """A job appearing in multiple query responses is emitted once."""
    payload = {
        "data": {
            "results": [
                {
                    "id": 999,
                    "title": "ML Engineer",
                    "department": "Engineering",
                    "location": {"country": "USA", "region": "California", "city": "San Francisco", "countryName": "United States"},
                    "creationDate": "2026-04-01T00:00:00.000Z",
                    "allLocations": [
                        {"country": "USA", "region": "California", "city": "San Francisco", "countryName": "United States"}
                    ],
                }
            ]
        }
    }
    session = _UberFakeSession(payload)
    jobs = sources.fetch_uber(session=session)
    assert len(jobs) == 1
    # But the source still issued one POST per query (dedupe is in-process).
    assert len(session.calls) == len(sources.UBER_QUERIES)


def test_uber_handles_missing_alllocations():
    """Falls back to the singular ``location`` field when allLocations missing."""
    payload = {
        "data": {
            "results": [
                {
                    "id": 1,
                    "title": "ML Engineer",
                    "department": "Engineering",
                    "location": {"country": "USA", "region": "California", "city": "Palo Alto", "countryName": "United States"},
                    "creationDate": "",
                }
            ]
        }
    }
    jobs = sources.fetch_uber(session=_UberFakeSession(payload))
    assert len(jobs) == 1
    assert jobs[0]["location"] == "Palo Alto, California"


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
    monkeypatch.setattr(sources, "fetch_aws", lambda session=None: [])
    monkeypatch.setattr(sources, "fetch_zap_surgical", lambda session=None: [])
    monkeypatch.setattr(sources, "fetch_uber", lambda session=None: [])
    monkeypatch.setattr(sources, "fetch_google", lambda: [])

    result = sources.fetch_all()
    assert result == sentinel_jobs


def test_fetch_all_both_sources_succeed(monkeypatch):
    monkeypatch.setattr(sources, "DISABLED_SOURCES", set())
    monkeypatch.setattr(sources, "fetch_handshake", lambda session=None: [{"id": "handshake:a"}])
    monkeypatch.setattr(sources, "fetch_zoox", lambda session=None: [{"id": "zoox:b"}])
    monkeypatch.setattr(sources, "fetch_aws", lambda session=None: [{"id": "aws:c"}])
    monkeypatch.setattr(sources, "fetch_zap_surgical", lambda session=None: [{"id": "zap:d"}])
    monkeypatch.setattr(sources, "fetch_uber", lambda session=None: [{"id": "uber:f"}])
    monkeypatch.setattr(sources, "fetch_google", lambda: [{"id": "google:e"}])
    result = sources.fetch_all()
    assert [j["id"] for j in result] == [
        "handshake:a", "zoox:b", "aws:c", "zap:d", "uber:f", "google:e"
    ]


def test_fetch_all_skips_disabled_sources(monkeypatch):
    """Names listed in DISABLED_SOURCES are skipped without invoking the fetcher."""
    monkeypatch.setattr(sources, "DISABLED_SOURCES", {"google", "aws"})
    monkeypatch.setattr(sources, "fetch_handshake", lambda session=None: [{"id": "handshake:a"}])
    monkeypatch.setattr(sources, "fetch_zoox", lambda session=None: [{"id": "zoox:b"}])
    monkeypatch.setattr(sources, "fetch_zap_surgical", lambda session=None: [{"id": "zap:d"}])
    monkeypatch.setattr(sources, "fetch_uber", lambda session=None: [{"id": "uber:f"}])

    def _should_not_be_called(*a, **kw):
        raise AssertionError("disabled fetcher was invoked")

    monkeypatch.setattr(sources, "fetch_aws", _should_not_be_called)
    monkeypatch.setattr(sources, "fetch_google", _should_not_be_called)

    result = sources.fetch_all()
    assert [j["id"] for j in result] == ["handshake:a", "zoox:b", "zap:d", "uber:f"]


class _AwsFakeSession:
    """Session that returns a sequence of canned responses for amazon.jobs.

    Any call to ``sources.AWS_SEARCH_URL`` pops the next queued payload.
    Calls to other URLs return an empty-jobs payload so higher-level loops
    terminate immediately.
    """

    def __init__(self, queue):
        self._queue = list(queue)
        self.calls: list[dict] = []

    def get(self, url, timeout=None, params=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        if url == sources.AWS_SEARCH_URL:
            if not self._queue:
                return _FakeResponse({"jobs": [], "hits": 0})
            return _FakeResponse(self._queue.pop(0))
        # Any unexpected URL — return empty to keep loops short.
        return _FakeResponse({"jobs": [], "hits": 0})


def _empty_aws_page():
    return {"jobs": [], "hits": 0}


def test_aws_normalizes_fixture():
    payload = _load_fixture("aws_sample.json")
    # Serve the same payload once; subsequent queries for other locations
    # come back empty so the loop terminates.
    session = _AwsFakeSession([payload])

    jobs = sources.fetch_aws(session=session)

    # Only the AWS job should survive the company filter (fixture has 1 AWS
    # + 1 retail/finance role).
    assert len(jobs) == 1
    j = jobs[0]
    assert set(j.keys()) == REQUIRED_KEYS
    assert j["id"].startswith("aws:")
    assert j["company"] == "AWS"
    # posted_date "April 20, 2026" -> ISO 2026-04-20T00:00:00+00:00
    assert j["posted_at"] == "2026-04-20T00:00:00+00:00"
    assert j["url"].startswith("https://www.amazon.jobs/en/jobs/")
    assert j["remote"] is False


def test_aws_filters_non_aws_company():
    payload = {
        "hits": 2,
        "jobs": [
            {
                "id_icims": "111",
                "title": "AWS SDE",
                "job_category": "Software Development",
                "location": "US, CA, San Francisco",
                "posted_date": "April 1, 2026",
                "job_path": "/en/jobs/111/aws-sde",
                "company_name": "Amazon Web Services, Inc.",
                "business_category": "aws",
            },
            {
                "id_icims": "222",
                "title": "Warehouse Associate",
                "job_category": "Fulfillment & Operations Management",
                "location": "US, CA, San Francisco",
                "posted_date": "April 1, 2026",
                "job_path": "/en/jobs/222/warehouse",
                "company_name": "Amazon.com Services LLC",
                "business_category": "customer-fulfillment",
            },
        ],
    }
    session = _AwsFakeSession([payload])
    jobs = sources.fetch_aws(session=session)
    assert [j["id"] for j in jobs] == ["aws:111"]


def test_aws_paginates():
    # First page full (100 jobs) -> fetcher requests a second page.
    # Second page short (<100) -> fetcher stops for this loc_query.
    # All jobs after that come from empty pages (subsequent loc_query loops).
    def _mk_job(iid):
        return {
            "id_icims": str(iid),
            "title": "AWS SDE",
            "job_category": "Software Development",
            "location": "US, CA, San Francisco",
            "posted_date": "April 1, 2026",
            "job_path": f"/en/jobs/{iid}/aws-sde",
            "company_name": "Amazon Web Services, Inc.",
            "business_category": "aws",
        }

    page1 = {"hits": 150, "jobs": [_mk_job(i) for i in range(100)]}
    page2 = {"hits": 150, "jobs": [_mk_job(i) for i in range(100, 150)]}
    session = _AwsFakeSession([page1, page2])

    jobs = sources.fetch_aws(session=session)

    # 150 unique AWS jobs from the first loc_query. Subsequent loc_queries
    # see empty pages and contribute nothing.
    assert len(jobs) == 150
    # Exactly 2 calls consumed the queued pages; remaining loc_queries each
    # issued 1 call that returned empty. 6 loc_queries -> 2 + 5 = 7 calls.
    aws_calls = [c for c in session.calls if c["url"] == sources.AWS_SEARCH_URL]
    assert len(aws_calls) == 7
    # Second call should be offset=100 for the first loc_query.
    assert aws_calls[0]["params"]["offset"] == 0
    assert aws_calls[1]["params"]["offset"] == 100
    # Third call resets offset to 0 (new loc_query).
    assert aws_calls[2]["params"]["offset"] == 0


def test_aws_handles_missing_posted_date():
    payload = {
        "hits": 2,
        "jobs": [
            {
                "id_icims": "333",
                "title": "AWS SDE",
                "job_category": "Software Development",
                "location": "US, CA, San Francisco",
                "posted_date": "",
                "job_path": "/en/jobs/333/aws-sde",
                "company_name": "Amazon Web Services, Inc.",
                "business_category": "aws",
            },
            {
                "id_icims": "444",
                "title": "AWS SDE",
                "job_category": "Software Development",
                "location": "US, CA, San Francisco",
                "posted_date": "not a real date",
                "job_path": "/en/jobs/444/aws-sde",
                "company_name": "Amazon Web Services, Inc.",
                "business_category": "aws",
            },
        ],
    }
    session = _AwsFakeSession([payload])
    jobs = sources.fetch_aws(session=session)
    assert len(jobs) == 2
    for j in jobs:
        assert j["posted_at"] == ""


def test_zap_surgical_normalizes_fixture():
    payload = _load_fixture("zap_sample.json")
    session = _FakeSession({sources.ZAP_SURGICAL_URL: payload})

    jobs = sources.fetch_zap_surgical(session=session)

    assert len(jobs) == 1
    j = jobs[0]
    assert set(j.keys()) == REQUIRED_KEYS
    assert j["id"].startswith("zap:")
    assert j["company"] == "Zap Surgical"
    raw = payload["content"][0]
    assert j["title"] == raw["name"]
    assert j["department"] == raw["department"]["label"]
    # city, region concatenation
    assert j["location"] == "Sunnyvale, CA"
    assert j["url"] == raw["ref"]
    assert j["posted_at"] == raw["releasedDate"]
    assert j["remote"] is False


def test_zap_surgical_empty_response():
    session = _FakeSession(
        {
            sources.ZAP_SURGICAL_URL: {
                "offset": 0,
                "limit": 100,
                "totalFound": 0,
                "content": [],
            }
        }
    )
    jobs = sources.fetch_zap_surgical(session=session)
    assert jobs == []


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
