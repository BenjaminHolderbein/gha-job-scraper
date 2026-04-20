"""Pure filter predicates for normalized job dicts.

A job dict has the shape:
    {"id": str, "company": str, "title": str, "department": str,
     "location": str, "remote": bool, "url": str, "posted_at": str}

`matches(job)` returns True iff the job passes all filters:
  - title matches at least one TITLE_PATTERNS regex
  - title does NOT contain any SENIORITY_REJECT entry
  - location is acceptable given the company's HQ (see `matches_location`)
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

TITLE_PATTERNS: list[re.Pattern] = [
    # ML/AI/CV/NLP role with engineer/scientist/researcher noun — word-order flexible
    re.compile(
        r"\b(machine learning|ml|deep learning|dl|artificial intelligence|ai|computer vision|cv|nlp|perception)\b"
        r".*\b(engineer|scientist|researcher)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(engineer|scientist|researcher)\b"
        r".*\b(machine learning|ml|deep learning|dl|computer vision|cv|nlp|perception)\b",
        re.IGNORECASE,
    ),
    # Canonical standalone titles
    re.compile(r"\b(applied scientist|research scientist|research engineer|data scientist)\b", re.IGNORECASE),
    # Abbreviation-only roles
    re.compile(r"\b(mle|aie)\b", re.IGNORECASE),
]

SENIORITY_REJECT: list[str] = [
    "Senior",
    "Sr.",
    "Staff",
    "Principal",
    "Lead",
    "Director",
    "Manager",
    "Head of",
    "VP",
    "Vice President",
    "Intern",
    "Student",
]

LOCATION_ALLOW: list[str] = [
    "San Francisco",
    "SF Bay",
    "Bay Area",
    "Palo Alto",
    "Mountain View",
    "Foster City",
    "Redwood City",
    "South San Francisco",
    "San Jose",
    "Santa Clara",
    "Sunnyvale",
    "Cupertino",
    "Menlo Park",
    "Berkeley",
    "Oakland",
    "Emeryville",
    "Hayward",
    "Fremont",
    "Milpitas",
    "Burlingame",
    "Millbrae",
    "San Mateo",
    "Daly City",
    "Alameda",
]

US_REMOTE_TOKENS: list[str] = [
    "Remote - US",
    "Remote (US)",
    "Remote, US",
    "Remote US",
    "Remote - United States",
    "Remote (United States)",
    "United States",
    "USA",
    "US Remote",
    "Remote-US",
    "Anywhere in US",
    "Anywhere in the US",
    "Remote, USA",
]

# Company HQ lookup — True if HQ is in Bay Area (we accept remote roles for these).
# False → we only accept physical Bay Area roles, reject remote.
COMPANY_HQ_IN_BAY_AREA: dict[str, bool] = {
    "Handshake": True,
    "Zoox": True,
    "Zap Surgical": True,
    "Google": True,
    "AWS": False,
}

# Locations that, combined with remote=True, we treat as ambiguous-US remote.
_AMBIGUOUS_REMOTE_LOCATIONS = {"", "remote", "remote - anywhere"}

# Clearly non-US remote markers: if a remote job's location contains any of
# these (and no US token), reject.
_NON_US_REMOTE_HINTS = [
    "europe",
    "emea",
    "uk",
    "united kingdom",
    "canada",
    "apac",
    "asia",
    "australia",
    "india",
    "germany",
    "france",
    "ireland",
    "netherlands",
    "latam",
    "mexico",
    "brazil",
    "argentina",
    "japan",
    "china",
    "singapore",
]


def _ci_contains_any(haystack: str, needles: list[str]) -> bool:
    """Case-insensitive substring match against any needle."""
    h = haystack.lower()
    return any(n.lower() in h for n in needles)


def matches_title(title: str) -> bool:
    """True if the title matches any TITLE_PATTERNS regex."""
    if not title:
        return False
    return any(p.search(title) for p in TITLE_PATTERNS)


def is_senior(title: str) -> bool:
    """True if the title looks senior/managerial (should be rejected).

    Uses word-boundary matching for the short tokens that could match inside
    other words (e.g. "VP" inside "VPN"), and also handles the "Sr" / "Sr."
    special cases without tripping on words like "first".
    """
    if not title:
        return False
    lowered = title.lower()

    # Word-boundary tokens (avoid false positives like "VPN" matching "VP").
    word_boundary_tokens = {
        "senior",
        "staff",
        "principal",
        "lead",
        "director",
        "manager",
        "vp",
        "vice president",
        "intern",
        "student",
    }
    for token in word_boundary_tokens:
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            return True

    # "Head of" — substring is fine, it's specific enough.
    if "head of" in lowered:
        return True

    # "Sr." — literal, distinctive enough to substring-match.
    if "sr." in lowered:
        return True

    # " Sr " — only match as a standalone token with surrounding whitespace
    # (padding the title on both sides catches start/end cases) to avoid
    # false positives inside words like "first".
    if " sr " in f" {lowered} ":
        return True

    return False


def _company_hq_in_bay_area(company: str) -> bool:
    """Return True if company HQ is in the Bay Area.

    Unknown companies default to False (conservative) and emit a warning.
    """
    if not company:
        log.warning("matches_location: empty company, defaulting to non-BA HQ")
        return False
    if company not in COMPANY_HQ_IN_BAY_AREA:
        log.warning("matches_location: unknown company %r, defaulting to non-BA HQ", company)
        return False
    return COMPANY_HQ_IN_BAY_AREA[company]


def matches_location(location: str, remote: bool, company: str) -> bool:
    """True if the location is acceptable.

    Acceptance rules:
      1. Physical Bay Area match → accept, regardless of company HQ.
      2. Explicit US-remote token in location → accept IFF company HQ is in Bay Area.
      3. remote=True + ambiguous location ("", "Remote", "Remote - Anywhere") → accept
         IFF company HQ is in Bay Area.
      4. remote=True + clearly non-US location → reject.
      5. Otherwise → reject.
    """
    loc = (location or "").strip()
    loc_lower = loc.lower()

    # Rule 1: physical Bay Area match wins regardless of company.
    if _ci_contains_any(loc, LOCATION_ALLOW):
        return True

    hq_in_ba = _company_hq_in_bay_area(company)

    # Rule 2: explicit US-remote token.
    if _ci_contains_any(loc, US_REMOTE_TOKENS):
        return hq_in_ba

    if remote:
        # Rule 4: explicit non-US location → reject.
        if any(hint in loc_lower for hint in _NON_US_REMOTE_HINTS):
            return False
        # Rule 3: ambiguous-remote → accept iff BA HQ.
        if loc_lower in _AMBIGUOUS_REMOTE_LOCATIONS:
            return hq_in_ba
        # Remote flag set but location is some other city/string not in our
        # allowlist and not obviously non-US: be conservative and reject.
        return False

    # Rule 5: not remote and not in allowlist.
    return False


def matches(job: dict) -> bool:
    """True if the job passes title, seniority, and location filters."""
    title = job.get("title", "") or ""
    location = job.get("location", "") or ""
    remote = bool(job.get("remote", False))
    company = job.get("company", "") or ""

    if not matches_title(title):
        return False
    if is_senior(title):
        return False
    if not matches_location(location, remote, company):
        return False
    return True
