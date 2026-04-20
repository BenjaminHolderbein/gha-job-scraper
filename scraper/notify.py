"""Notification channels: email (Gmail SMTP) and mobile push (ntfy.sh)."""
from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from itertools import groupby
from operator import itemgetter

import requests

log = logging.getLogger(__name__)

NTFY_URL = "https://ntfy.sh"


def _group_by_company(jobs: list[dict]) -> list[tuple[str, list[dict]]]:
    """Stable alphabetical grouping by company."""
    sorted_jobs = sorted(jobs, key=itemgetter("company"))
    return [(company, list(group)) for company, group in groupby(sorted_jobs, key=itemgetter("company"))]


def _format_location(job: dict) -> str:
    loc = job.get("location", "")
    if job.get("remote"):
        return f"{loc} · Remote" if loc else "Remote"
    return loc


def _build_plain_body(jobs: list[dict]) -> str:
    lines: list[str] = []
    groups = _group_by_company(jobs)
    for i, (company, group) in enumerate(groups):
        if i > 0:
            lines.append("")
        lines.append(company)
        for job in group:
            lines.append(f"  - {job['title']} — {_format_location(job)}")
            lines.append(f"    {job['url']}")
    return "\n".join(lines) + "\n"


def _build_html_body(jobs: list[dict]) -> str:
    parts = ["<html><body>"]
    for company, group in _group_by_company(jobs):
        parts.append(f"<h3>{company}</h3><ul>")
        for job in group:
            loc = _format_location(job)
            parts.append(
                f'<li><strong>{job["title"]}</strong> — {loc}<br>'
                f'<a href="{job["url"]}">{job["url"]}</a></li>'
            )
        parts.append("</ul>")
    parts.append("</body></html>")
    return "".join(parts)


def send_email(new_jobs: list[dict]) -> None:
    """Send email via Gmail SMTP. Skip silently if jobs list is empty."""
    if not new_jobs:
        return
    address = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n = len(new_jobs)

    msg = EmailMessage()
    msg["Subject"] = f"New ML/AI/DS roles — {today} ({n} new)"
    msg["From"] = address
    msg["To"] = address
    msg.set_content(_build_plain_body(new_jobs))
    msg.add_alternative(_build_html_body(new_jobs), subtype="html")

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(address, password)
        smtp.send_message(msg)


def _build_ntfy_body(jobs: list[dict]) -> str:
    counts = [(company, len(group)) for company, group in _group_by_company(jobs)]
    summary = " · ".join(f"{company}: {count}" for company, count in counts)

    titles = [job["title"] for job in jobs]
    shown = titles[:5]
    remaining = len(titles) - len(shown)
    title_lines = [f"- {t}" for t in shown]
    if remaining > 0:
        title_lines.append(f"+{remaining} more")

    return summary + "\n\n" + "\n".join(title_lines)


def send_ntfy(new_jobs: list[dict]) -> None:
    """Send mobile push via ntfy.sh. Skip silently if jobs list is empty."""
    if not new_jobs:
        return
    topic = os.environ["NTFY_TOPIC"]
    n = len(new_jobs)

    headers = {
        "Title": f"{n} new ML/AI/DS roles",
        "Priority": "high" if n >= 3 else "default",
        "Tags": "briefcase",
        "Click": new_jobs[0]["url"],
    }
    body = _build_ntfy_body(new_jobs)

    resp = requests.post(
        f"{NTFY_URL}/{topic}",
        data=body.encode("utf-8"),
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()


def notify(new_jobs: list[dict]) -> list[str]:
    """Dispatch to all enabled channels. Returns names of channels that ran successfully.

    One channel failing logs the exception but does NOT raise — the other still runs.
    If no channels configured, logs a warning and returns [].
    """
    if not new_jobs:
        return []

    channels: list[tuple[str, callable]] = []
    if os.getenv("GMAIL_ADDRESS") and os.getenv("GMAIL_APP_PASSWORD"):
        channels.append(("email", send_email))
    if os.getenv("NTFY_TOPIC"):
        channels.append(("ntfy", send_ntfy))

    if not channels:
        log.warning(
            "no notification channels configured; new jobs: %d", len(new_jobs)
        )
        return []

    succeeded: list[str] = []
    for name, fn in channels:
        try:
            fn(new_jobs)
            succeeded.append(name)
        except Exception:
            log.exception("channel %s failed", name)
    return succeeded
