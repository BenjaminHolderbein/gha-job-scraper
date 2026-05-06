# gha-job-scraper

Scheduled GitHub Actions workflow that scrapes companies' careers pages for ML/AI/DS individual-contributor roles in the SF Bay Area (and US-remote, where the company is BA-headquartered) and notifies on new matches via email and/or mobile push.

## Sources

Each source is a `fetch_<company>()` function in [`scraper/sources.py`](scraper/sources.py) that returns a normalized job dict. `fetch_all()` is the canonical list of currently active sources. Most use a public ATS JSON endpoint (Ashby, Lever, SmartRecruiters, amazon.jobs); JS-rendered career pages use Playwright (headless Chromium).

## Filtering

See [`scraper/filters.py`](scraper/filters.py). Three predicates, all must pass:

- **Title** matches an ML/AI/DS IC pattern (regex-based, word-order flexible) — see `TITLE_PATTERNS`.
- **Seniority** does not match a senior/managerial token — see `SENIORITY_REJECT`.
- **Location** is acceptable per `matches_location()`: physical Bay Area always wins; remote roles accepted only when the company's HQ is in the Bay Area (`COMPANY_HQ_IN_BAY_AREA`).

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
3. Add an entry to `COMPANY_HQ_IN_BAY_AREA` in `scraper/filters.py` (`True` if HQ is Bay Area and remote roles should be accepted; `False` to restrict to physical Bay Area only).
4. Wire into `fetch_all()` in `sources.py`.
5. Add an offline fixture + test in `tests/test_sources.py`, and a `@pytest.mark.live` test in `tests/test_live_sources.py`.
