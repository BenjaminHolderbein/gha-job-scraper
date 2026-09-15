"""Unit tests for scraper.filters."""

from __future__ import annotations

import pytest

from scraper.filters import (
    is_rejected_department,
    is_rejected_title,
    is_senior,
    matches,
    matches_location,
    matches_title,
)


def _job(**overrides) -> dict:
    base = {
        "id": "job-1",
        "company": "Handshake",
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
        matches(
            _job(
                title="ML Engineer",
                location="New York, NY",
                remote=False,
                company="Handshake",
            )
        )
        is False
    )


def test_filter_accepts_us_remote() -> None:
    assert (
        matches(
            _job(
                title="Data Scientist",
                location="Remote - US",
                remote=True,
                company="Handshake",
            )
        )
        is True
    )


def test_filter_rejects_eu_remote() -> None:
    assert (
        matches(
            _job(
                title="Data Scientist",
                location="Remote - Europe",
                remote=True,
                company="Handshake",
            )
        )
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
# matches_title — ACCEPT
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        # Word-order-flexible ML/AI role + noun
        "Engineer, Machine Learning",
        "Software Engineer, ML",
        "Scientist, Applied ML",
        "Deep Learning Engineer",
        "Computer Vision Engineer",
        "Perception Engineer",
        "NLP Engineer",
        "ML Scientist",
        "AI Engineer",
        "Machine Learning Engineer",
        "machine learning engineer",  # case-insensitive
        "ML Engineer",
        "Research Engineer, Robotics",
        # Canonical standalone titles
        "Applied Scientist",
        "Applied Scientist, Search",
        "Research Scientist",
        "Research Engineer",
        "Data Scientist",
        # Abbreviation-only roles
        "MLE",
        "MLE - Ranking",
        "AIE",
        "AIE Infra",
        "AI Engineer, Platform",
        # Forward Deployed Engineer variants
        "Forward Deployed Engineer",
        "Forward-Deployed Engineer",
        "Forward Deployed AI Engineer",
        "Forward Deployed Software Engineer - SF",
        "Forward Deployed Engineer, GenAI",
        "Forward Deployed Infrastructure Engineer, New Grad",
        "AI Engineer - FDE (Forward Deployed Engineer)",
        "FDE",
    ],
)
def test_matches_title_true(title: str) -> None:
    assert matches_title(title) is True


# ---------------------------------------------------------------------------
# matches_title — REJECT
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineer",
        "Backend Engineer",
        "Product Manager",
        "DevOps Engineer",
        "Sales Engineer",
        "Designer",
        "",
        # Forward Deployed without an engineering noun
        "Forward Deployed Product Manager, Enterprise",
        "Deployment Strategist - Japan Forward Deployed",
        "Pre-Sales Program Lead, Forward Deployed Engineering",
    ],
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
        "AI PhD Student Researcher",
        "ML Student Researcher",
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
# matches_location — physical Bay Area (rule 1, company-agnostic)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "location",
    [
        "San Francisco, CA",
        "SF Bay Area",
        "Palo Alto, CA",
        "Mountain View",
        "Foster City, CA",
        "Redwood City",
        "South San Francisco, CA",
        "San Jose, CA",
        "Sunnyvale, CA",
        "Berkeley, CA",
        "Oakland, CA",
        "Menlo Park, CA",
    ],
)
@pytest.mark.parametrize("company", ["Handshake", "AWS", "UnknownCo"])
def test_matches_location_physical_bay_area_accept(
    location: str, company: str
) -> None:
    assert matches_location(location, remote=False, company=company) is True


# ---------------------------------------------------------------------------
# matches_location — per-company HQ logic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "company,location,remote,expected",
    [
        # BA HQ + US remote → accept
        ("Handshake", "Remote - US", True, True),
        ("Handshake", "Remote (US)", True, True),
        ("Handshake", "United States", True, True),
        ("Zoox", "US Remote", True, True),
        # BA HQ + ambiguous remote → accept
        ("Handshake", "", True, True),
        ("Handshake", "Remote", True, True),
        ("Handshake", "Remote - Anywhere", True, True),
        # BA HQ + non-US remote → reject
        ("Handshake", "Remote - Europe", True, False),
        ("Handshake", "London, UK", True, False),
        # Non-BA HQ + physical BA → accept (rule 1 wins)
        ("AWS", "Sunnyvale, CA", False, True),
        ("AWS", "Palo Alto, CA", False, True),
        # Non-BA HQ + US remote → reject
        ("AWS", "Remote - US", True, False),
        ("AWS", "United States", True, False),
        # Non-BA HQ + ambiguous remote → reject
        ("AWS", "", True, False),
        ("AWS", "Remote", True, False),
        # Non-BA HQ + non-BA physical → reject
        ("AWS", "Seattle, WA", False, False),
        # Unknown company defaults to non-BA HQ
        ("UnknownCo", "Remote - US", True, False),
        ("UnknownCo", "", True, False),
        # Unknown company + physical BA still accepts
        ("UnknownCo", "San Francisco, CA", False, True),
        # remote=False + empty/remote string → reject regardless
        ("Handshake", "", False, False),
        ("Handshake", "Remote", False, False),
        # Bare country string ("United States") → US-anywhere
        ("Handshake", "United States", False, True),
        ("Handshake", "USA", False, True),
        ("AWS", "United States", False, False),
        # Physical non-BA US city spelled with the country → NOT remote
        ("Handshake", "Atlanta, Georgia, United States", False, False),
        ("Handshake", "Chicago, Illinois, United States", False, False),
        ("Handshake", "Tysons, Virginia, United States", False, False),
        # ...but "Remote" anywhere in the string still counts
        ("Handshake", "Remote - United States", False, True),
        ("Handshake", "Remote-Friendly, United States", False, True),
    ],
)
def test_matches_location_company_hq(
    company: str, location: str, remote: bool, expected: bool
) -> None:
    assert matches_location(location, remote=remote, company=company) is expected


# ---------------------------------------------------------------------------
# matches_location — off-site physical rejects (company-agnostic among BA HQ)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "location",
    [
        "New York, NY",
        "Seattle, WA",
        "Austin, TX",
    ],
)
def test_matches_location_offsite_reject(location: str) -> None:
    assert matches_location(location, remote=False, company="Handshake") is False


# ---------------------------------------------------------------------------
# matches(job) — end-to-end smoke, company wiring
# ---------------------------------------------------------------------------


def test_matches_wires_company_through() -> None:
    # AWS + Remote-US → rejected because AWS HQ not in Bay Area
    job = _job(
        company="AWS",
        title="Data Scientist",
        location="Remote - US",
        remote=True,
    )
    assert matches(job) is False


def test_matches_missing_company_rejects_remote() -> None:
    # Missing company → unknown → defaults non-BA → remote rejected
    job = _job(
        company="",
        title="Data Scientist",
        location="Remote - US",
        remote=True,
    )
    assert matches(job) is False


# ---------------------------------------------------------------------------
# Hardware / department rejects
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "ASIC Design Engineer, Cloud-Scale Machine Learning Acceleration team - Annapurna Labs",
        "Physical Design Engineer - Static Timing Analysis, Annapurna Labs, Cloud Scale Machine Learning",
        "EMIR Engineer, Annapurna Labs - Cloud Scale Machine Learning",
        "AI SoC Modeling Engineer, Annapurna Labs Machine Learning Accelerators, AWS",
        "Hardware Development Engineer, AI/ML Server Development",
        "Manufacturing hardware engineer, Cloud AI/ML/storage server teams",
        "Cloud Hardware Dev Engineer (AWS Generative AI & ML Servers)",
        "Forward Deployed Engineer - Mixed Reality",
        "AI Support Engineer - San Francisco",
    ],
)
def test_is_rejected_title_true(title: str) -> None:
    assert is_rejected_title(title) is True
    assert matches(_job(company="AWS", title=title, location="Cupertino, California, USA")) is False


@pytest.mark.parametrize(
    "title",
    [
        "Applied Scientist, AWS Agentic AI",
        "ML Compiler Engineer, Annapurna Labs",
        "Software Development Engineer I, ML Infra Services, Annapurna Labs",
        "Forward Deployed Engineer",
        "",
    ],
)
def test_is_rejected_title_false(title: str) -> None:
    assert is_rejected_title(title) is False


def test_department_reject_hardware_development() -> None:
    assert is_rejected_department("Hardware Development") is True
    assert is_rejected_department("Software Development") is False
    assert is_rejected_department("") is False
    # ML-flavored title in a hardware department is rejected
    job = _job(
        company="AWS",
        title="Virtual Platform Software Engineer, Machine Learning Accelerators",
        department="Hardware Development",
        location="Cupertino, California, USA",
    )
    assert matches(job) is False
    assert matches({**job, "department": "Software Development"}) is True


def test_fde_bay_area_accepted_and_seniority_still_applies() -> None:
    assert matches(_job(company="Handshake", title="Forward Deployed Engineer")) is True
    assert matches(_job(company="Handshake", title="Manager, Forward Deployed Engineering")) is False
    # Non-BA-HQ company + remote-US → rejected
    assert matches(_job(company="AWS", title="Forward Deployed Engineer", location="United States", remote=True)) is False
    # BA-HQ company + remote-US → accepted
    assert matches(_job(company="Zoox", title="AI Engineer - FDE (Forward Deployed Engineer)", location="United States", remote=True)) is True
