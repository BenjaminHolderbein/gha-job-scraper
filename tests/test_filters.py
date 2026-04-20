"""Unit tests for scraper.filters."""

from __future__ import annotations

import pytest

from scraper.filters import (
    is_senior,
    matches,
    matches_location,
    matches_title,
)


def _job(**overrides) -> dict:
    base = {
        "id": "job-1",
        "company": "TestCo",
        "title": "Machine Learning Engineer",
        "department": "Engineering",
        "location": "San Francisco, CA",
        "remote": False,
        "url": "https://example.com/job-1",
        "posted_at": "2026-04-20",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Required named tests
# ---------------------------------------------------------------------------


def test_filter_accepts_mle_title() -> None:
    assert matches(_job(title="Machine Learning Engineer")) is True


def test_filter_rejects_senior() -> None:
    assert matches(_job(title="Senior ML Engineer")) is False


def test_filter_rejects_offsite_location() -> None:
    assert (
        matches(_job(title="ML Engineer", location="New York, NY", remote=False))
        is False
    )


def test_filter_accepts_us_remote() -> None:
    assert (
        matches(_job(title="Data Scientist", location="Remote - US", remote=True))
        is True
    )


def test_filter_rejects_eu_remote() -> None:
    assert (
        matches(_job(title="Data Scientist", location="Remote - Europe", remote=True))
        is False
    )


def test_filter_rejects_non_matching_title() -> None:
    assert matches(_job(title="Software Engineer")) is False


@pytest.mark.parametrize(
    "title",
    ["Staff ML Engineer", "Principal AI Engineer"],
)
def test_filter_rejects_staff_and_principal(title: str) -> None:
    assert matches(_job(title=title)) is False


# ---------------------------------------------------------------------------
# matches_title
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Machine Learning Engineer",
        "machine learning engineer",  # case-insensitive
        "ML Engineer",
        "MLE - Ranking",
        "AI Engineer, Platform",
        "AIE Infra",
        "Data Scientist",
        "Applied Scientist, Search",
        "Research Scientist",
        "Research Engineer",
    ],
)
def test_matches_title_true(title: str) -> None:
    assert matches_title(title) is True


@pytest.mark.parametrize(
    "title",
    ["Software Engineer", "Product Manager", "Designer", "", "Backend Engineer"],
)
def test_matches_title_false(title: str) -> None:
    assert matches_title(title) is False


# ---------------------------------------------------------------------------
# is_senior
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Senior ML Engineer",
        "Sr. Data Scientist",
        "Data Scientist, Sr.",
        "Staff ML Engineer",
        "Principal AI Engineer",
        "Lead Applied Scientist",
        "Engineering Manager, ML",
        "Director of ML",
        "Head of Data Science",
        "VP, Engineering",
        "Vice President, AI",
        "ML Engineer Sr",  # " Sr " style (trailing, padded on match)
        "Machine Learning Engineer Intern",
        "Data Science Intern",
    ],
)
def test_is_senior_true(title: str) -> None:
    assert is_senior(title) is True


@pytest.mark.parametrize(
    "title",
    [
        "Machine Learning Engineer",
        "ML Engineer",
        "Data Scientist",
        "Research Engineer, first year",  # "first" must not match "sr"
        "VPN Engineer",  # word-boundary check prevents VPN → VP
        "Internal Tools ML Engineer",  # word-boundary prevents Internal → Intern
        "",
    ],
)
def test_is_senior_false(title: str) -> None:
    assert is_senior(title) is False


# ---------------------------------------------------------------------------
# matches_location
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "location,remote",
    [
        ("San Francisco, CA", False),
        ("SF Bay Area", False),
        ("Palo Alto, CA", False),
        ("Mountain View", False),
        ("Foster City, CA", False),
        ("Redwood City", False),
        ("South San Francisco, CA", False),
        ("Remote - US", True),
        ("Remote (US)", True),
        ("Remote, US", True),
        ("United States", True),
        ("", True),  # ambiguous remote → accept
        ("Remote", True),
        ("Remote - Anywhere", True),
    ],
)
def test_matches_location_true(location: str, remote: bool) -> None:
    assert matches_location(location, remote) is True


@pytest.mark.parametrize(
    "location,remote",
    [
        ("New York, NY", False),
        ("Seattle, WA", False),
        ("Remote - Europe", True),
        ("Remote - UK", True),
        ("Remote - Canada", True),
        ("London, UK", True),
        ("Berlin, Germany", True),
        ("", False),  # not remote, empty → reject
        ("Remote", False),  # remote=False but location says remote → reject
    ],
)
def test_matches_location_false(location: str, remote: bool) -> None:
    assert matches_location(location, remote) is False
