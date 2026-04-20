"""Tests for scraper.state."""
from __future__ import annotations

from scraper import state


def test_load_missing_returns_empty(tmp_path):
    path = tmp_path / "does_not_exist.json"
    assert state.load(path) == {}


def test_load_empty_file_returns_empty(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")
    assert state.load(path) == {}


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "seen.json"
    data = {"zoox:abc": "2026-04-20T00:00:00+00:00", "handshake:xyz": "2026-04-20T00:00:01+00:00"}
    state.save(data, path)
    loaded = state.load(path)
    assert loaded == data
    # Should end with trailing newline
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_diff_returns_only_new():
    seen = {"A": "2026-04-19T00:00:00+00:00"}
    current = [
        {"id": "A", "company": "X", "title": "t1", "department": "", "location": "",
         "remote": False, "url": "", "posted_at": ""},
        {"id": "B", "company": "X", "title": "t2", "department": "", "location": "",
         "remote": False, "url": "", "posted_at": ""},
    ]
    new_jobs = state.diff(current, seen)
    assert len(new_jobs) == 1
    assert new_jobs[0]["id"] == "B"


def test_update_adds_new_without_mutation():
    seen = {"A": "2026-04-19T00:00:00+00:00"}
    original = dict(seen)
    new_jobs = [
        {"id": "B", "company": "X", "title": "t", "department": "", "location": "",
         "remote": False, "url": "", "posted_at": ""},
        {"id": "C", "company": "X", "title": "t", "department": "", "location": "",
         "remote": False, "url": "", "posted_at": ""},
    ]
    now_iso = "2026-04-20T12:00:00+00:00"
    result = state.update(seen, new_jobs, now_iso)

    # Original untouched
    assert seen == original
    # New dict contains old + new
    assert result["A"] == "2026-04-19T00:00:00+00:00"
    assert result["B"] == now_iso
    assert result["C"] == now_iso
