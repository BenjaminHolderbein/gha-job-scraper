"""Tests for scraper.filters (referral-watch mode)."""

from __future__ import annotations

import pytest

from scraper.filters import (
    is_rejected_title,
    matches,
    matches_department,
    matches_location,
    matches_title,
)


def _job(
    title: str = "Data Scientist",
    company: str = "Handshake",
    department: str = "Data",
    location: str = "San Francisco, CA",
    remote: bool = False,
) -> dict:
    return {
        "id": "handshake:x",
        "company": company,
        "title": title,
        "department": department,
        "location": location,
        "remote": remote,
        "url": "https://jobs.ashbyhq.com/handshake/x",
        "posted_at": "2026-10-29T00:00:00+00:00",
    }


@pytest.mark.parametrize(
    "title",
    [
        "Data Scientist",
        "Senior Data Scientist",
        "Staff Data Scientist, Handshake AI",
        "Data Science Manager",
        "Head of Data Science",
        "Data Scientist Intern",
        "Applied Scientist",
        "Research Scientist, Handshake AI",
        "Machine Learning Scientist",
    ],
)
def test_matches_title_true(title: str) -> None:
    assert matches_title(title) is True


@pytest.mark.parametrize(
    "title",
    [
        "",
        "Software Engineer",
        "Data Engineer",
        "Senior Cloud Engineer",
        "Product Manager, Handshake AI",
        "Computer Science Student Ambassador",
    ],
)
def test_matches_title_false(title: str) -> None:
    assert matches_title(title) is False


@pytest.mark.parametrize(
    "title",
    [
        "Handshake AI Fellow Experience Specialist, Contract",
        "Data Science Fellow",
        "PhD Data Scientist - AI Trainer",
        "Data Science Expert (Contractor)",
        "Freelance Data Scientist",
    ],
)
def test_is_rejected_title_true(title: str) -> None:
    assert is_rejected_title(title) is True


@pytest.mark.parametrize("title", ["Data Scientist", "Senior Data Scientist, Growth"])
def test_is_rejected_title_false(title: str) -> None:
    assert is_rejected_title(title) is False


def test_matches_department() -> None:
    assert matches_department("Data Science") is True
    assert matches_department("Data Science & Analytics") is True
    assert matches_department("Engineering") is False
    assert matches_department("") is False


def test_matches_any_level() -> None:
    assert matches(_job(title="Senior Data Scientist")) is True
    assert matches(_job(title="Data Science Manager")) is True


@pytest.mark.parametrize(
    "location",
    [
        "San Francisco, CA",
        "San Francisco",
        "New York, NY; San Francisco, CA",
        "Remote (USA); San Francisco, CA",
    ],
)
def test_matches_location_true(location: str) -> None:
    assert matches_location(location) is True
    assert matches(_job(location=location)) is True


@pytest.mark.parametrize(
    "location",
    ["", "New York, NY", "Remote (USA)", "London, UK", "Palo Alto, CA"],
)
def test_matches_location_false(location: str) -> None:
    assert matches_location(location) is False
    assert matches(_job(location=location)) is False


def test_matches_via_department_only() -> None:
    assert matches(_job(title="Analytics Lead", department="Data Science")) is True
    assert matches(_job(title="Analytics Lead", department="Product")) is False


def test_matches_rejects_contract_roles() -> None:
    assert matches(_job(title="Data Scientist, Contract")) is False
    assert matches(_job(title="Handshake AI Fellow", department="Data Science")) is False


def test_matches_rejects_non_target_company() -> None:
    assert matches(_job(company="Google")) is False
    assert matches(_job(company="")) is False
