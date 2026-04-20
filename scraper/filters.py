"""Pure filter predicates for normalized job dicts.

A job dict has the shape:
    {"id": str, "company": str, "title": str, "department": str,
     "location": str, "remote": bool, "url": str, "posted_at": str}

`matches(job)` returns True iff the job passes all filters:
  - title contains at least one TITLE_KEYWORDS entry
  - title does NOT contain any SENIORITY_REJECT entry
  - location is in-range (SF Bay Area) OR is an acceptable US remote
"""

from __future__ import annotations

import re

TITLE_KEYWORDS: list[str] = [
    "Machine Learning Engineer",
    "ML Engineer",
    "MLE",
    "AI Engineer",
    "AIE",
    "Data Scientist",
    "Applied Scientist",
    "Research Scientist",
    "Research Engineer",
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
]

US_REMOTE_TOKENS: list[str] = [
    "Remote - US",
    "Remote (US)",
    "Remote, US",
    "Remote US",
    "United States",
    "USA",
]

# Locations that, combined with remote=True, we treat as ambiguous-US remote
# (accepted — we'd rather false-positive than miss a remote role).
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
    """True if the title contains at least one target keyword."""
    if not title:
        return False
    return _ci_contains_any(title, TITLE_KEYWORDS)


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


def matches_location(location: str, remote: bool) -> bool:
    """True if the location is acceptable.

    Acceptance rules:
      1. Location contains any LOCATION_ALLOW token (SF Bay Area).
      2. Location contains any US_REMOTE_TOKENS entry.
      3. remote=True AND location is empty / generic "Remote" / "Remote - Anywhere"
         → ambiguous; accept (false positive preferred over miss).
      4. Otherwise, if remote=True but location clearly names a non-US region,
         reject.
    """
    loc = (location or "").strip()
    loc_lower = loc.lower()

    # Rule 1: in-range physical location.
    if _ci_contains_any(loc, LOCATION_ALLOW):
        return True

    # Rule 2: US remote tokens (accept regardless of the `remote` flag — the
    # string itself is explicit).
    if _ci_contains_any(loc, US_REMOTE_TOKENS):
        return True

    if remote:
        # Rule 3: ambiguous-remote → accept.
        if loc_lower in _AMBIGUOUS_REMOTE_LOCATIONS:
            return True
        # Rule 4: explicit non-US remote → reject.
        if any(hint in loc_lower for hint in _NON_US_REMOTE_HINTS):
            return False
        # Remote flag set but location is some other city/string not in our
        # allowlist and not obviously non-US: be conservative and reject.
        return False

    # Not remote and not in our allowlist.
    return False


def matches(job: dict) -> bool:
    """True if the job passes title, seniority, and location filters."""
    title = job.get("title", "") or ""
    location = job.get("location", "") or ""
    remote = bool(job.get("remote", False))

    if not matches_title(title):
        return False
    if is_senior(title):
        return False
    if not matches_location(location, remote):
        return False
    return True
