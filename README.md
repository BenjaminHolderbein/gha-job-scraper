# gha-job-scraper

Scheduled GitHub Actions workflow that scrapes Handshake (via Ashby) and Zoox
(via Lever) for ML/AI/DS individual-contributor roles and notifies on new
matches via email and/or mobile push.

## Run locally

```bash
uv sync
export GMAIL_ADDRESS=you@gmail.com
export GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
export NTFY_TOPIC=your-long-random-topic
uv run python -m scraper.main
```

At least one notification channel must be configured, otherwise new jobs are
only logged.

## Configuration

Set as GitHub Actions secrets (or local env vars):

| Secret               | Purpose                                  | Required |
|----------------------|------------------------------------------|----------|
| `GMAIL_ADDRESS`      | Gmail account used as sender + recipient | Optional (enables email; both email vars required together) |
| `GMAIL_APP_PASSWORD` | 16-char Gmail App Password (needs 2FA)   | Optional (enables email) |
| `NTFY_TOPIC`         | ntfy.sh topic name (treat as secret)     | Optional (enables mobile push) |

At least one channel (email or ntfy) must be configured.

## Schedule

Runs 4 times per day on US-business-hours weekdays (8am, 11am, 2pm, 5pm PT,
Mon-Fri) via GitHub Actions cron. Also triggerable manually via
`workflow_dispatch`. After each run, the workflow commits the updated
`seen_jobs.json` dedup state back to `main` with `[skip ci]`, which also keeps
the schedule alive past GitHub's 60-day inactivity shutoff.
