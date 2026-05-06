"""Job source fetchers.

Each fetcher returns a list of normalized job dicts of the shape:
    {id, company, title, department, location, remote, url, posted_at}

No filtering is applied here (beyond source-specific sanity filters like
dropping non-AWS roles from amazon.jobs) — these functions return what the
upstream APIs report. Title/keyword filtering happens in ``filters.py``.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests

log = logging.getLogger(__name__)

HANDSHAKE_URL = "https://api.ashbyhq.com/posting-api/job-board/handshake"
ZOOX_URL = "https://api.lever.co/v0/postings/zoox?mode=json"
AWS_SEARCH_URL = "https://www.amazon.jobs/en/search.json"
ZAP_SURGICAL_URL = (
    "https://api.smartrecruiters.com/v1/companies/zap-surgical/postings"
)
UBER_URL = "https://www.uber.com/api/loadSearchJobsResults"
TIMEOUT = 30

# --- Uber careers ------------------------------------------------------------
# Uber's public search endpoint requires an x-csrf-token header but does not
# validate its value. The API ignores ``limit`` and returns all matching jobs
# in a single response, so we issue one POST per query and dedupe by id.
UBER_QUERIES = [
    "machine learning",
    "data scientist",
    "research scientist",
    "research engineer",
    "applied scientist",
    "deep learning",
    "computer vision",
]
UBER_HEADERS = {
    "Content-Type": "application/json",
    "x-csrf-token": "x",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# --- Google careers (Playwright-based) ---------------------------------------
GOOGLE_CAREERS_BASE = "https://www.google.com/about/careers/applications/"
GOOGLE_RESULTS_URL = GOOGLE_CAREERS_BASE + "jobs/results"
GOOGLE_QUERIES = [
    '"machine learning"',
    '"data scientist"',
    '"research engineer"',
    '"research scientist"',
    '"applied scientist"',
    '"deep learning"',
]
GOOGLE_LOCATIONS = [
    "Mountain View, CA, USA",
    "San Francisco, CA, USA",
    "Sunnyvale, CA, USA",
]
GOOGLE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
GOOGLE_PAGE_CAP = 5
GOOGLE_NAV_TIMEOUT_MS = 15_000
GOOGLE_TOTAL_BUDGET_S = 90.0
_GOOGLE_JOB_ID_RE = re.compile(r"jobs/results/(\d+)")

# Bay Area location queries used to enumerate amazon.jobs for AWS roles.
AWS_LOC_QUERIES = [
    "San Francisco, California",
    "Sunnyvale, California",
    "Palo Alto, California",
    "Santa Clara, California",
    "San Jose, California",
    "Cupertino, California",
]
AWS_PAGE_SIZE = 100
AWS_MAX_RESULTS_PER_QUERY = 500


def _get(
    session: requests.Session | None, url: str, params: dict | None = None
) -> requests.Response:
    s = session if session is not None else requests
    resp = s.get(url, params=params, timeout=TIMEOUT) if params is not None else s.get(url, timeout=TIMEOUT)
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


def _is_aws_job(job: dict) -> bool:
    """Pragmatic AWS filter for amazon.jobs.

    amazon.jobs returns every Amazon role (retail, ops, whole foods, etc.).
    Accept a job if either:
      - ``company_name`` contains "Amazon Web Services" or "AWS", OR
      - ``business_category`` is "aws" (Amazon's own taxonomy — catches the
        bulk of AWS engineering roles whose employer entity is e.g.
        "Amazon Development Center U.S., Inc.").
    """
    company = (job.get("company_name") or "")
    if "Amazon Web Services" in company or "AWS" in company:
        return True
    if (job.get("business_category") or "").lower() == "aws":
        return True
    return False


def _parse_amazon_posted_date(s: str) -> str:
    """Parse amazon.jobs' human-format date (e.g. "April  8, 2026") to ISO.

    Returns ``""`` on failure (and logs a warning). strptime tolerates the
    double-space that amazon.jobs emits for single-digit days.
    """
    if not s:
        return ""
    try:
        return (
            datetime.strptime(s.strip(), "%B %d, %Y")
            .replace(tzinfo=timezone.utc)
            .isoformat()
        )
    except ValueError:
        log.warning("aws: could not parse posted_date %r", s)
        return ""


def _normalize_aws(job: dict) -> dict:
    return {
        "id": f"aws:{job['id_icims']}",
        "company": "AWS",
        "title": job.get("title", "") or "",
        "department": job.get("job_category", "") or "",
        "location": job.get("location", "") or "",
        "remote": False,
        "url": "https://www.amazon.jobs" + (job.get("job_path", "") or ""),
        "posted_at": _parse_amazon_posted_date(job.get("posted_date", "") or ""),
    }


def _normalize_zap(job: dict) -> dict:
    loc = job.get("location") or {}
    city = (loc.get("city") or "").strip()
    region = (loc.get("region") or "").strip()
    location = ", ".join(p for p in (city, region) if p)
    dept = (job.get("department") or {}).get("label", "") or ""
    url = job.get("ref") or ""
    if not url:
        url = f"https://jobs.smartrecruiters.com/ZAP/{job.get('id', '')}"
    return {
        "id": f"zap:{job['id']}",
        "company": "Zap Surgical",
        "title": job.get("name", "") or "",
        "department": dept,
        "location": location,
        "remote": False,
        "url": url,
        "posted_at": job.get("releasedDate", "") or "",
    }


def _format_uber_location(job: dict) -> str:
    """Build a single 'City, Region; City, Region' location string from allLocations.

    Falls back to the singular ``location`` field if ``allLocations`` is empty.
    """
    locs = job.get("allLocations") or []
    if not locs:
        single = job.get("location")
        if single:
            locs = [single]
    parts: list[str] = []
    for loc in locs:
        city = (loc.get("city") or "").strip()
        region = (loc.get("region") or "").strip()
        country = (loc.get("countryName") or loc.get("country") or "").strip()
        # For non-US, include country name so location filters can detect
        # foreign postings; for US, "City, Region" is enough.
        if country and country not in ("USA", "United States"):
            piece = ", ".join(p for p in (city, region, country) if p)
        else:
            piece = ", ".join(p for p in (city, region) if p)
        if piece:
            parts.append(piece)
    return "; ".join(parts)


def _normalize_uber(job: dict) -> dict:
    return {
        "id": f"uber:{job['id']}",
        "company": "Uber",
        "title": job.get("title", "") or "",
        "department": job.get("department", "") or "",
        "location": _format_uber_location(job),
        "remote": False,
        "url": f"https://www.uber.com/global/en/careers/list/{job['id']}/",
        "posted_at": job.get("creationDate", "") or "",
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


def fetch_aws(session: requests.Session | None = None) -> list[dict]:
    """Fetch AWS jobs from amazon.jobs search.json across Bay Area queries.

    Paginates each location query with ``result_limit=100`` until the page
    comes back short or ``AWS_MAX_RESULTS_PER_QUERY`` is reached. Dedupes
    across queries by ``id_icims``. Filters to AWS-only roles via
    :func:`_is_aws_job`.
    """
    by_id: dict[str, dict] = {}
    for loc_query in AWS_LOC_QUERIES:
        offset = 0
        while offset < AWS_MAX_RESULTS_PER_QUERY:
            params = {
                "base_query": "",
                "loc_query": loc_query,
                "result_limit": AWS_PAGE_SIZE,
                "offset": offset,
            }
            resp = _get(session, AWS_SEARCH_URL, params=params)
            payload = resp.json()
            jobs = payload.get("jobs") or []
            for j in jobs:
                iid = j.get("id_icims")
                if not iid or iid in by_id:
                    continue
                if not _is_aws_job(j):
                    continue
                by_id[iid] = _normalize_aws(j)
            if len(jobs) < AWS_PAGE_SIZE:
                break
            hits = payload.get("hits")
            if isinstance(hits, int) and offset + AWS_PAGE_SIZE >= hits:
                break
            offset += AWS_PAGE_SIZE
    return list(by_id.values())


def fetch_zap_surgical(session: requests.Session | None = None) -> list[dict]:
    """Fetch Zap Surgical jobs from SmartRecruiters and normalize.

    SmartRecruiters paginates via ``offset``/``limit``. As of writing,
    ``zap-surgical`` returns zero jobs; the fetcher handles that gracefully.
    """
    results: list[dict] = []
    offset = 0
    limit = 100
    while True:
        params = {"offset": offset, "limit": limit}
        resp = _get(session, ZAP_SURGICAL_URL, params=params)
        payload = resp.json()
        content = payload.get("content") or []
        for j in content:
            results.append(_normalize_zap(j))
        total = payload.get("totalFound")
        if len(content) < limit:
            break
        offset += limit
        if isinstance(total, int) and offset >= total:
            break
    return results


def fetch_uber(session: requests.Session | None = None) -> list[dict]:
    """Fetch Uber jobs from the public careers search API across ML queries.

    Issues one POST per query in :data:`UBER_QUERIES`, dedupes by job id, and
    returns normalized job dicts. The API ignores the ``limit`` field, so a
    single page per query is sufficient. ``location`` filtering is left to
    :mod:`scraper.filters` since Uber returns ``allLocations`` per posting.
    """
    s = session if session is not None else requests
    by_id: dict[int, dict] = {}
    for query in UBER_QUERIES:
        body = {"params": {"query": query, "limit": 1000, "page": 0}}
        resp = s.post(UBER_URL, json=body, headers=UBER_HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        results = ((payload.get("data") or {}).get("results")) or []
        for job in results:
            jid = job.get("id")
            if jid is None or jid in by_id:
                continue
            by_id[jid] = _normalize_uber(job)
    return list(by_id.values())


def _parse_google_job_card(card: dict) -> dict | None:
    """Normalize a raw Google career job card dict into the standard shape.

    Expected input keys (all strings unless noted):
        title:     job title (``h3`` text)
        company:   employer name (usually "Google", sometimes "YouTube", etc.)
        locations: list[str] of location strings (one per ``place`` entry)
        href:      anchor href — either absolute or relative to
                   ``jobs/results/``; must contain the numeric Google job id

    Returns the normalized job dict or ``None`` if the card is missing the
    fields we need (title/href/id).
    """
    title = (card.get("title") or "").strip()
    href = (card.get("href") or "").strip()
    if not title or not href:
        return None
    m = _GOOGLE_JOB_ID_RE.search(href)
    if not m:
        return None
    job_id = m.group(1)

    if href.startswith("http"):
        url = href
    elif href.startswith("/"):
        url = "https://www.google.com" + href
    else:
        # relative href like "jobs/results/..." — resolve against the careers
        # base so we don't double-up the "jobs/results/" segment.
        url = urljoin(GOOGLE_CAREERS_BASE, href)

    locations = card.get("locations") or []
    if not isinstance(locations, list):
        locations = [str(locations)]
    location = "; ".join(loc.strip() for loc in locations if loc and loc.strip())

    company = (card.get("company") or "Google").strip() or "Google"

    return {
        "id": f"google:{job_id}",
        "company": company,
        "title": title,
        "department": "",
        "location": location,
        "remote": False,
        "url": url,
        "posted_at": "",
    }


def _google_extract_cards(page: Any) -> list[dict]:
    """Extract raw card dicts from a loaded Google careers results page.

    Runs in the browser via ``page.evaluate`` so that one round-trip yields
    structured data for every listitem on the current page. Returns an empty
    list if the results container never renders.
    """
    # Wait for at least one job card to appear. If the selector times out,
    # this page had zero results — return [] and let the caller move on.
    try:
        page.wait_for_selector(
            "ul[role='list'] > li, main ul li", timeout=GOOGLE_NAV_TIMEOUT_MS
        )
    except Exception:
        log.info("google: no job list rendered")
        return []

    js = """
    () => {
      const out = [];
      // Try a few container selectors — Google has tweaked this over time.
      const lists = document.querySelectorAll("main ul");
      let items = [];
      for (const ul of lists) {
        const lis = ul.querySelectorAll(":scope > li");
        if (lis.length > items.length) items = Array.from(lis);
      }
      for (const li of items) {
        const h3 = li.querySelector("h3");
        const title = h3 ? h3.textContent.trim() : "";
        if (!title) continue;
        // Company: the generic next to the `corporate_fare` icon.
        let company = "";
        const corp = Array.from(li.querySelectorAll("*")).find(
          (el) => el.textContent.trim() === "corporate_fare"
        );
        if (corp && corp.parentElement) {
          const sibs = corp.parentElement.querySelectorAll("*");
          for (const s of sibs) {
            const t = s.textContent.trim();
            if (t && t !== "corporate_fare") { company = t; break; }
          }
        }
        // Locations: siblings of the `place` icon (skipping separators like ";").
        const locations = [];
        const placeIcon = Array.from(li.querySelectorAll("*")).find(
          (el) => el.textContent.trim() === "place"
        );
        if (placeIcon && placeIcon.parentElement) {
          for (const child of placeIcon.parentElement.children) {
            const t = child.textContent.trim();
            if (!t || t === "place") continue;
            // Skip "+N more" aggregator spans.
            if (/^\\+\\d+ more$/.test(t)) continue;
            // Strip leading "; " if present.
            locations.push(t.replace(/^;\\s*/, ""));
          }
        }
        // Canonical link.
        let href = "";
        const a = li.querySelector("a[href*='jobs/results/']");
        if (a) href = a.getAttribute("href") || "";
        out.push({ title, company, locations, href });
      }
      return out;
    }
    """
    try:
        raw = page.evaluate(js)
    except Exception:
        log.exception("google: page.evaluate failed")
        return []
    if not isinstance(raw, list):
        return []
    return raw


def fetch_google() -> list[dict]:
    """Scrape careers.google.com for ML/AI/DS roles in Bay Area locations.

    Uses Playwright's ``sync_api``. Iterates the cross-product of
    :data:`GOOGLE_QUERIES` x :data:`GOOGLE_LOCATIONS`, paginates each search
    up to :data:`GOOGLE_PAGE_CAP` pages, and dedupes the merged results by
    Google's internal job id. Returns an empty list (no exception) on
    Playwright import failure, launch failure, or if every search combo
    produced zero results.

    Also bounded by :data:`GOOGLE_TOTAL_BUDGET_S` wall-clock seconds as a
    safety net.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        log.exception("google: playwright not available; skipping")
        return []

    deadline = time.monotonic() + GOOGLE_TOTAL_BUDGET_S
    by_id: dict[str, dict] = {}

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception:
                log.exception("google: chromium launch failed")
                return []
            try:
                context = browser.new_context(user_agent=GOOGLE_USER_AGENT)
                page = context.new_page()
                page.set_default_timeout(GOOGLE_NAV_TIMEOUT_MS)

                for query in GOOGLE_QUERIES:
                    for location in GOOGLE_LOCATIONS:
                        if time.monotonic() > deadline:
                            log.warning("google: wall-clock budget exhausted")
                            break
                        url = (
                            f"{GOOGLE_RESULTS_URL}"
                            f"?q={requests.utils.quote(query)}"
                            f"&location={requests.utils.quote(location)}"
                        )
                        for page_num in range(1, GOOGLE_PAGE_CAP + 1):
                            if time.monotonic() > deadline:
                                break
                            page_url = (
                                url if page_num == 1 else f"{url}&page={page_num}"
                            )
                            try:
                                page.goto(
                                    page_url,
                                    timeout=GOOGLE_NAV_TIMEOUT_MS,
                                    wait_until="domcontentloaded",
                                )
                            except Exception:
                                log.exception(
                                    "google: navigation failed for %s", page_url
                                )
                                break
                            cards = _google_extract_cards(page)
                            if not cards:
                                # No results on this page → stop paginating.
                                break
                            new_on_page = 0
                            for card in cards:
                                job = _parse_google_job_card(card)
                                if job is None:
                                    continue
                                if job["id"] in by_id:
                                    continue
                                by_id[job["id"]] = job
                                new_on_page += 1
                            log.info(
                                "google: q=%r loc=%r page=%d cards=%d new=%d",
                                query,
                                location,
                                page_num,
                                len(cards),
                                new_on_page,
                            )
                            # If the page held fewer than a typical page size,
                            # we're almost certainly on the last page.
                            if len(cards) < 20:
                                break
                    else:
                        continue
                    break
            finally:
                try:
                    browser.close()
                except Exception:
                    log.exception("google: browser close failed")
    except Exception:
        log.exception("google: unexpected failure during scrape")
        return []

    if not by_id:
        log.warning("google: produced zero jobs across all search combos")
        return []
    return list(by_id.values())


def fetch_all() -> list[dict]:
    """Fetch from all sources, concatenating results.

    If one source fails, the exception is logged and the others' results are
    still returned.
    """
    all_jobs: list[dict] = []
    for name, fn in (
        ("handshake", fetch_handshake),
        ("zoox", fetch_zoox),
        ("aws", fetch_aws),
        ("zap_surgical", fetch_zap_surgical),
        ("uber", fetch_uber),
        ("google", fetch_google),
    ):
        try:
            jobs = fn()
        except Exception:
            log.exception("source %s failed", name)
            continue
        log.info("source %s returned %d jobs", name, len(jobs))
        all_jobs.extend(jobs)
    return all_jobs
