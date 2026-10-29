# gha-job-scraper

Scheduled GitHub Actions workflow that watches Handshake's careers board (which also carries Handshake AI roles) and notifies via email and/or mobile push when a new data science role posts, so you can refer a friend for it.

## Sources

Each source is a `fetch_<company>()` function in [`scraper/sources.py`](scraper/sources.py) that returns a normalized job dict. `fetch_all()` is the canonical list of sources, and `DISABLED_SOURCES` turns individual sources off.

Active: Handshake (Ashby). The earlier job-search sources (CodeRabbit, Zoox, AWS, Zap Surgical, Uber, Google) remain in the code but are disabled. Remove a source from `DISABLED_SOURCES` and add its company to `TARGET_COMPANIES` to turn it back on.

## Filtering

See [`scraper/filters.py`](scraper/filters.py). A job matches when:

- **Company** is in `TARGET_COMPANIES`.
- **Title** matches a data science pattern ("Data Scientist", "Data Science ...", any "... Scientist"), **or** the department is in `DEPARTMENT_ALLOW` ("Data Science").
- **Not a contract/AI-training gig**: the title has no `TITLE_REJECT` token (Contract, Fellow, Trainer, Expert, ...). Handshake AI posts many such roles on the same board, and they aren't referable.

Seniority and location are deliberately not filtered, since a role at any level or office might suit a friend.

## Run locally

```bash
uv sync
uv run playwright install chromium
export GMAIL_ADDRESS=you@gmail.com
export GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
export NTFY_TOPIC=your-long-random-topic
uv run python -m scraper.main
```

At least one notification channel must be configured, otherwise new jobs are only logged.

## Configuration

Set as GitHub Actions secrets (or local env vars):

| Secret               | Purpose                                  | Required |
|----------------------|------------------------------------------|----------|
| `GMAIL_ADDRESS`      | Gmail account used as sender + recipient | Optional (enables email; both email vars required together) |
| `GMAIL_APP_PASSWORD` | 16-char Gmail App Password (needs 2FA)   | Optional (enables email) |
| `NTFY_TOPIC`         | ntfy.sh topic name (treat as secret)     | Optional (enables mobile push) |

At least one channel (email or ntfy) must be configured.

## Schedule

Runs 4 times per day on US-business-hours weekdays (8am, 11am, 2pm, 5pm PT, Mon-Fri) via GitHub Actions cron. Also triggerable manually via `workflow_dispatch`. After each run, the workflow commits the updated `seen_jobs.json` dedup state back to `main` with `[skip ci]`, which also keeps the schedule alive past GitHub's 60-day inactivity shutoff.

## Tests

```bash
uv run pytest                 # offline tests, default
uv run pytest -m live         # live tests against real upstream APIs
```

The `live` suite verifies each source's real endpoint still returns well-formed jobs. It runs daily via the [`Live source check`](.github/workflows/live-check.yml) workflow, which opens (or comments on) a GitHub issue labeled `live-check-failure` when a source breaks.

## Adding a company

1. Identify the ATS (try Greenhouse, Lever, Ashby, SmartRecruiters JSON endpoints first; fall back to Playwright for JS-rendered sites).
2. Add a `fetch_<company>()` in `scraper/sources.py` that returns the normalized shape `{id, company, title, department, location, remote, url, posted_at}`.
3. Add the company name to `TARGET_COMPANIES` in `scraper/filters.py`.
4. Wire into `fetch_all()` in `sources.py`.
5. Add an offline fixture + test in `tests/test_sources.py`, and a `@pytest.mark.live` test in `tests/test_live_sources.py`.
