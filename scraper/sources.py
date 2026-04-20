"""Job source fetchers for Handshake (Ashby) and Zoox (Lever).

Each fetcher returns a list of normalized job dicts of the shape:
    {id, company, title, department, location, remote, url, posted_at}

No filtering is applied here — these functions return every job the upstream
API reports.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

HANDSHAKE_URL = "https://api.ashbyhq.com/posting-api/job-board/handshake"
ZOOX_URL = "https://api.lever.co/v0/postings/zoox?mode=json"
TIMEOUT = 30


def _get(session: requests.Session | None, url: str) -> requests.Response:
    s = session if session is not None else requests
    resp = s.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp


def _normalize_ashby(job: dict) -> dict:
    return {
        "id": f"handshake:{job['id']}",
        "company": "Handshake",
        "title": job.get("title", ""),
        "department": job.get("department", "") or "",
        "location": job.get("location", "") or "",
        "remote": bool(job.get("isRemote", False)),
        "url": job.get("jobUrl") or job.get("applyUrl") or "",
        "posted_at": job.get("publishedAt", ""),
    }


def _normalize_lever(job: dict) -> dict:
    categories = job.get("categories") or {}
    created_ms = job.get("createdAt")
    if isinstance(created_ms, (int, float)):
        posted_at = datetime.fromtimestamp(
            created_ms / 1000, tz=timezone.utc
        ).isoformat()
    else:
        posted_at = ""
    return {
        "id": f"zoox:{job['id']}",
        "company": "Zoox",
        "title": job.get("text", ""),
        "department": categories.get("department", "") or "",
        "location": categories.get("location", "") or "",
        "remote": job.get("workplaceType") == "remote",
        "url": job.get("hostedUrl", ""),
        "posted_at": posted_at,
    }


def fetch_handshake(session: requests.Session | None = None) -> list[dict]:
    """Fetch Handshake jobs from Ashby and normalize."""
    resp = _get(session, HANDSHAKE_URL)
    payload = resp.json()
    jobs = payload.get("jobs", [])
    return [_normalize_ashby(j) for j in jobs]


def fetch_zoox(session: requests.Session | None = None) -> list[dict]:
    """Fetch Zoox jobs from Lever and normalize."""
    resp = _get(session, ZOOX_URL)
    payload = resp.json()
    # Lever returns a raw JSON array.
    return [_normalize_lever(j) for j in payload]


def fetch_all() -> list[dict]:
    """Fetch from all sources, concatenating results.

    If one source fails, the exception is logged and the other's results are
    still returned.
    """
    all_jobs: list[dict] = []
    for name, fn in (("handshake", fetch_handshake), ("zoox", fetch_zoox)):
        try:
            jobs = fn()
        except Exception:
            log.exception("source %s failed", name)
            continue
        log.info("source %s returned %d jobs", name, len(jobs))
        all_jobs.extend(jobs)
    return all_jobs
