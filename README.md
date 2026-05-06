# gha-job-scraper

Scheduled GitHub Actions workflow that scrapes multiple companies' careers pages for ML/AI/DS individual-contributor roles and notifies on new matches via email and/or mobile push.

## Sources

| Company      | ATS / method      | Endpoint                                                         |
|--------------|-------------------|------------------------------------------------------------------|
| Handshake    | Ashby (JSON)      | `api.ashbyhq.com/posting-api/job-board/handshake`                |
| Zoox         | Lever (JSON)      | `api.lever.co/v0/postings/zoox?mode=json`                        |
| AWS          | amazon.jobs (JSON, undocumented) | `www.amazon.jobs/en/search.json`                    |
| Zap Surgical | SmartRecruiters (JSON)           | `api.smartrecruiters.com/v1/companies/zap-surgical/postings` |
| Google       | Playwright (headless Chromium)   | `www.google.com/about/careers/applications/jobs/results`   |

Alphabet subsidiaries (YouTube, DeepMind) are captured incidentally via the Google careers board and matched when they post Bay Area roles.

## Filtering

**Title patterns** (regex, word-order flexible): accepts Machine Learning / ML / Deep Learning / AI / Computer Vision / NLP / Perception combined with Engineer / Scientist / Researcher; canonical titles (Applied Scientist, Research Scientist/Engineer, Data Scientist); and abbreviations (MLE, AIE).

**Seniority reject:** Senior, Staff, Principal, Lead, Director, Manager, VP, Head of, Intern, Student.

**Location / remote policy:**
- Physical Bay Area (24 cities including SF, Palo Alto, Mountain View, Foster City, San Jose, Sunnyvale, Berkeley, Oakland, etc.) → accept.
- Remote roles → accept only when the company's HQ is in the Bay Area. AWS and other non-BA-HQ companies have remote roles rejected, Bay-local roles accepted.

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

## Adding a company

1. Identify the ATS (try Greenhouse, Lever, Ashby, SmartRecruiters JSON endpoints first; fall back to Playwright for JS-rendered sites).
2. Add a `fetch_<company>()` in `scraper/sources.py` that returns the normalized shape `{id, company, title, department, location, remote, url, posted_at}`.
3. Add an entry to `COMPANY_HQ_IN_BAY_AREA` in `scraper/filters.py` (`True` if HQ is Bay Area and remote roles should be accepted; `False` to restrict to physical Bay Area only).
4. Wire into `fetch_all()` in `sources.py`.
5. Add fixture + tests.
