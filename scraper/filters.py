"""Pure filter predicates for normalized job dicts.

A job dict has the shape:
    {"id": str, "company": str, "title": str, "department": str,
     "location": str, "remote": bool, "url": str, "posted_at": str}

The scraper runs in *referral-watch* mode: it flags roles worth referring a
friend to, so there is no seniority filtering — any level, as long as one of
the role's offices is in San Francisco. `matches(job)` returns True iff:
  - the company is in TARGET_COMPANIES
  - the title matches a TITLE_PATTERNS regex OR the department is in
    DEPARTMENT_ALLOW
  - the title does NOT contain any TITLE_REJECT token (contract / AI-training
    gigs posted on the same board, which aren't referable full-time roles)
  - the location mentions a LOCATION_ALLOW entry
"""

from __future__ import annotations

import re

TARGET_COMPANIES: set[str] = {"Handshake"}

TITLE_PATTERNS: list[re.Pattern] = [
    # "Data Scientist", "Data Science Manager", "Senior Data Scientist, Handshake AI"
    re.compile(r"\bdata scien(ce|tist)s?\b", re.IGNORECASE),
    # Applied / Research / Decision / ML Scientist and other *Scientist titles.
    re.compile(r"\bscientists?\b", re.IGNORECASE),
]

# Ashby department names that count as data science regardless of title.
DEPARTMENT_ALLOW: list[str] = [
    "Data Science",
]

# Handshake AI posts large numbers of contract expert/fellow roles (e.g.
# "Handshake AI Fellow ..., Contract", "PhD Data Scientist - AI Trainer") on
# the same Ashby board. Those aren't referral-eligible full-time roles.
TITLE_REJECT: list[str] = [
    "Contract",
    "Contractor",
    "Freelance",
    "Fellow",
    "Fellowship",
    "Trainer",
    "AI Training",
    "Tutor",
    "Annotator",
    "Expert",
]

# Case-insensitive substrings; a multi-office location ("New York, NY;
# San Francisco, CA") passes if any office matches.
LOCATION_ALLOW: list[str] = [
    "San Francisco",
]


def matches_title(title: str) -> bool:
    """True if the title matches any TITLE_PATTERNS regex."""
    if not title:
        return False
    return any(p.search(title) for p in TITLE_PATTERNS)


def matches_department(department: str) -> bool:
    """True if the department contains a DEPARTMENT_ALLOW entry."""
    if not department:
        return False
    d = department.lower()
    return any(a.lower() in d for a in DEPARTMENT_ALLOW)


def matches_location(location: str) -> bool:
    """True if the location contains a LOCATION_ALLOW entry."""
    if not location:
        return False
    loc = location.lower()
    return any(a.lower() in loc for a in LOCATION_ALLOW)


def is_rejected_title(title: str) -> bool:
    """True if the title contains a TITLE_REJECT token (word-boundary match)."""
    if not title:
        return False
    return any(
        re.search(rf"\b{re.escape(tok)}\b", title, re.IGNORECASE) for tok in TITLE_REJECT
    )


def matches(job: dict) -> bool:
    """True if the job is a referral-worthy SF data science role at a target company."""
    title = job.get("title", "") or ""
    department = job.get("department", "") or ""
    company = job.get("company", "") or ""
    location = job.get("location", "") or ""

    if company not in TARGET_COMPANIES:
        return False
    if not (matches_title(title) or matches_department(department)):
        return False
    if is_rejected_title(title):
        return False
    if not matches_location(location):
        return False
    return True
