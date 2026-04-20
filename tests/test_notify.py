"""Tests for scraper.notify."""
from __future__ import annotations

import smtplib

import pytest

from scraper import notify


def _job(jid: str, company: str = "Handshake", title: str = "Machine Learning Engineer",
         url: str = "https://example.com/job", location: str = "San Francisco, CA",
         remote: bool = False) -> dict:
    return {
        "id": jid,
        "company": company,
        "title": title,
        "department": "Eng",
        "location": location,
        "remote": remote,
        "url": url,
        "posted_at": "2026-04-20T00:00:00+00:00",
    }


def test_notify_no_channels_logs_and_returns_empty(monkeypatch, caplog):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("NTFY_TOPIC", raising=False)

    jobs = [_job("A")]
    with caplog.at_level("WARNING"):
        result = notify.notify(jobs)
    assert result == []


def test_notify_skips_when_empty_jobs(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "foo@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "password")
    monkeypatch.setenv("NTFY_TOPIC", "topic")

    def boom_smtp(*args, **kwargs):
        raise AssertionError("SMTP should not be called for empty jobs")

    def boom_post(*args, **kwargs):
        raise AssertionError("requests.post should not be called for empty jobs")

    monkeypatch.setattr(smtplib, "SMTP", boom_smtp)
    monkeypatch.setattr(notify.requests, "post", boom_post)

    assert notify.notify([]) == []
    # Also the individual functions skip silently:
    notify.send_email([])
    notify.send_ntfy([])


def test_send_ntfy_posts_expected_payload(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "bh-test-topic")

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, data=None, headers=None, timeout=None, **kwargs):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr(notify.requests, "post", fake_post)

    jobs = [
        _job("1", company="Handshake", title="ML Engineer",
             url="https://jobs.ashbyhq.com/handshake/abc"),
        _job("2", company="Handshake", title="Applied Scientist",
             url="https://jobs.ashbyhq.com/handshake/def"),
        _job("3", company="Zoox", title="Research Engineer",
             url="https://jobs.lever.co/zoox/xyz"),
    ]
    notify.send_ntfy(jobs)

    assert captured["url"] == "https://ntfy.sh/bh-test-topic"
    assert captured["timeout"] == 10

    headers = captured["headers"]
    assert headers["Title"] == "3 new ML/AI/DS roles"
    assert headers["Priority"] == "high"
    assert headers["Tags"] == "briefcase"
    assert headers["Click"] == "https://jobs.ashbyhq.com/handshake/abc"

    # All header values must latin-1 encode cleanly
    for v in headers.values():
        v.encode("latin-1")

    body = captured["data"].decode("utf-8")
    assert "Handshake: 2" in body
    assert "Zoox: 1" in body
    assert "- ML Engineer" in body
    assert "- Applied Scientist" in body
    assert "- Research Engineer" in body


def test_send_ntfy_priority_high_when_3_or_more(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "topic")

    captured_headers = []

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, data=None, headers=None, timeout=None, **kwargs):
        captured_headers.append(headers)
        return FakeResp()

    monkeypatch.setattr(notify.requests, "post", fake_post)

    notify.send_ntfy([_job("1"), _job("2")])
    assert captured_headers[-1]["Priority"] == "default"

    notify.send_ntfy([_job("1"), _job("2"), _job("3")])
    assert captured_headers[-1]["Priority"] == "high"


def test_notify_one_channel_failure_does_not_block_other(monkeypatch, caplog):
    monkeypatch.setenv("GMAIL_ADDRESS", "foo@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "password")
    monkeypatch.setenv("NTFY_TOPIC", "topic")

    # Make ntfy fail
    def failing_post(*args, **kwargs):
        raise RuntimeError("ntfy down")

    monkeypatch.setattr(notify.requests, "post", failing_post)

    # Record that SMTP was used
    smtp_calls = {"sent": 0, "login": 0, "starttls": 0}

    class FakeSMTP:
        def __init__(self, host, port):
            smtp_calls["host"] = host
            smtp_calls["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            smtp_calls["starttls"] += 1

        def login(self, addr, pw):
            smtp_calls["login"] += 1

        def send_message(self, msg):
            smtp_calls["sent"] += 1
            smtp_calls["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    jobs = [_job("A"), _job("B")]
    with caplog.at_level("ERROR"):
        result = notify.notify(jobs)

    assert result == ["email"]
    assert smtp_calls["sent"] == 1
    assert smtp_calls["login"] == 1
    assert smtp_calls["starttls"] == 1
    assert smtp_calls["host"] == "smtp.gmail.com"
    assert smtp_calls["port"] == 587
