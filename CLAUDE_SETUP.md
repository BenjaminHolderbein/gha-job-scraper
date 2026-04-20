# Job Scraper — Paste This To Claude Code

This file sets you up with a private GitHub Actions workflow that scrapes your target companies' job boards on a schedule and pushes you a phone notification (and optionally an email) the moment a matching role posts. Cost: $0. Maintenance: none.

Reference implementation: https://github.com/BenjaminHolderbein/gha-job-scraper

---

## Before you start

Install once on your machine:

- [Claude Code](https://claude.ai/code) — the CLI
- [`gh`](https://cli.github.com/) — GitHub CLI, then `gh auth login` (scopes: `repo`, `workflow`)
- [`uv`](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- [ntfy](https://ntfy.sh) mobile app — iOS or Android (for push notifications)

You'll also need:

- A Google account with 2FA enabled (if you want email notifications — optional)
- ~5 minutes of back-and-forth with Claude

---

## How to use this file

1. Create a new empty folder: `mkdir ~/job-scraper && cd ~/job-scraper`
2. Open Claude Code in that folder: `claude`
3. Paste everything below the `---PROMPT---` line into the Claude prompt
4. Answer Claude's questions when asked
5. Done

---PROMPT---

You are going to build me a GitHub Actions job scraper, modeled on https://github.com/BenjaminHolderbein/gha-job-scraper. Follow the steps below precisely. You have authorization to create files, create a private GitHub repo on my account (via `gh`), set GitHub secrets, and push commits. Do not ask me to confirm each sub-step — confirm scope once and execute the whole scope.

## Step 1 — Gather requirements (ask all at once, with recommendations)

Ask me these questions in a single batched message, each with a sensible default recommendation I can accept with "yes" or override:

1. **Target companies** (pick 2–4 to start): the companies whose careers pages you want scraped. I'll also ask about their ATS in Step 2.
2. **Role titles / keywords** to match (e.g., "Software Engineer", "Product Designer", "Data Scientist"). Case-insensitive substring match on job title.
3. **Seniority filter** — which of these should be *rejected*? Default reject set: `Senior, Sr., Staff, Principal, Lead, Director, Manager, Head of, VP, Vice President, Intern`. I can add or remove (e.g., new grads may want to keep "Intern"; senior engineers may want to drop "Senior").
4. **Locations to accept** — list cities/regions. Remote handling: should I accept US-remote? EU-remote? Ask me.
5. **Notification channels**:
   - **Push (ntfy.sh)** — free, no account. Recommend: yes. I'll auto-generate a random topic name.
   - **Email (Gmail SMTP)** — requires you to generate a Gmail App Password (https://myaccount.google.com/apppasswords, needs 2FA on the account). Recommend: yes, but optional — push alone works fine.
6. **Your email address** (for the email channel, if enabled).
7. **Repo name** — default `job-scraper`, private.
8. **Schedule** — default 4×/day on US weekdays at 8am/11am/2pm/5pm PT. Accept or customize.

Wait for my answers before proceeding.

## Step 2 — Discover each company's ATS

For each target company, determine which Applicant Tracking System (ATS) hosts their careers page. Try these in order — first match wins:

| ATS             | Public JSON endpoint template                                               |
|-----------------|-----------------------------------------------------------------------------|
| Greenhouse      | `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`                    |
| Lever           | `https://api.lever.co/v0/postings/{slug}?mode=json`                         |
| Ashby           | `https://api.ashbyhq.com/posting-api/job-board/{slug}`                      |
| SmartRecruiters | `https://api.smartrecruiters.com/v1/companies/{slug}/postings`              |

**Procedure per company:**

1. Guess the slug (usually the company name, lowercased, sometimes with/without "inc", "hq", or "careers"). Try a few variants.
2. For each guess, `curl` the 4 endpoints above. An HTTP 200 with a non-empty jobs array wins.
3. If all 4 fail, fetch the company's public careers page HTML with `curl` and grep for identifying markers (`greenhouse.io`, `lever.co`, `ashbyhq`, `smartrecruiters`, `ashby_jid=` in links, etc.). Use a web search if needed.
4. If the company uses **Workday, iCIMS, Taleo, BrassRing**, or another enterprise ATS with no public JSON: tell me, and recommend either (a) dropping that company from the list, or (b) scraping via Playwright as a fallback (much more fragile — not recommended for v1).

Report the ATS + slug + sample job count for each company back to me before writing code.

## Step 3 — Build the project

Create this exact layout (use `uv`, not pip):

```
{repo_name}/
├── .github/workflows/scrape.yml
├── scraper/
│   ├── __init__.py
│   ├── main.py          # orchestrator: fetch → filter → diff → notify → save state
│   ├── sources.py       # one fetcher per company, all normalize to common dict shape
│   ├── filters.py       # pure title/seniority/location predicates
│   ├── state.py         # seen_jobs.json dedup, atomic write
│   └── notify.py        # send_email + send_ntfy, independent channels
├── tests/
│   ├── __init__.py
│   ├── fixtures/        # one JSON file per ATS, real trimmed samples
│   ├── test_filters.py  # ≥5 tests
│   ├── test_sources.py  # fixture-based, no network
│   ├── test_state.py
│   └── test_notify.py   # mocks SMTP + requests.post
├── seen_jobs.json       # starts as `{}`
├── pyproject.toml       # deps: requests; dev: pytest; requires-python = ">=3.11"
├── uv.lock
├── .gitignore
└── README.md
```

**Normalized job dict** (returned by every source fetcher, consumed by everything downstream):

```python
{
    "id": str,        # "<ats>:<native_id>" — globally unique across sources
    "company": str,
    "title": str,
    "department": str,
    "location": str,
    "remote": bool,
    "url": str,
    "posted_at": str, # ISO8601 UTC
}
```

**ATS-specific field mappings** (use these — verified):

- **Ashby:** `id` → id; `title`, `department`, `location`, `isRemote`→remote, `jobUrl` (prefer) or `applyUrl`→url, `publishedAt`→posted_at
- **Lever:** `id`; `text`→title; `categories.department`, `categories.location`; `workplaceType == "remote"` → remote; `hostedUrl`→url; `createdAt` (ms epoch)→posted_at ISO
- **Greenhouse:** `id`; `title`; `departments[0].name`→department; `location.name`→location; `absolute_url`→url; `updated_at`→posted_at; remote has no standard field — infer from location string containing "Remote"
- **SmartRecruiters:** `id`; `name`→title; `department.label`→department; `location.city + location.region`→location; `ref`→url; `releasedDate`→posted_at

**Key design rules:**

- `sources.fetch_all()` wraps each source in try/except so one failure doesn't block others.
- Use `requests` with a 30s timeout. `response.raise_for_status()` on fetch.
- `filters.py` is pure: no I/O, no logging. Easy to unit-test.
- `state.py` atomic writes (write-tmp + `os.replace`).
- `notify.py` channel selection is env-var-driven:
  - Email enabled iff `GMAIL_ADDRESS` AND `GMAIL_APP_PASSWORD` set.
  - Push enabled iff `NTFY_TOPIC` set.
  - One channel failing logs but does not block the other.
- ntfy notification includes `Title`, `Priority` (`high` if ≥3 new else `default`), `Tags`, and `Click` (first job URL) headers. Body is compact ≤500 chars summary.

**Workflow file (`.github/workflows/scrape.yml`):**

```yaml
name: Scrape Jobs
on:
  schedule:
    # adjust to user's chosen schedule
    - cron: "0 15 * * 1-5"
    - cron: "0 18 * * 1-5"
    - cron: "0 21 * * 1-5"
    - cron: "0 0  * * 2-6"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  scrape:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen
      - name: Run scraper
        env:
          GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
        run: uv run python -m scraper.main
      - name: Commit updated state
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add seen_jobs.json
          git diff --staged --quiet || git commit -m "chore: update seen_jobs [skip ci]"
          git push
```

## Step 4 — Parallelize with sub-agents

To save context, spawn 4 sub-agents in parallel, each owning one slice:

1. **Scaffold agent** — `pyproject.toml`, `.gitignore`, `README.md`, `seen_jobs.json` = `{}`, empty `__init__.py` files, the workflow YAML.
2. **Sources agent** — `scraper/sources.py` + `tests/test_sources.py` + real-sample fixtures (fetch once via `curl`, trim to 2 jobs each).
3. **Filters agent** — `scraper/filters.py` + `tests/test_filters.py` (≥5 tests).
4. **State + notify agent** — `scraper/state.py`, `scraper/notify.py`, and their tests.

After they finish, write `scraper/main.py` yourself (small orchestrator — ~40 lines).

## Step 5 — Verify locally

1. `uv sync`
2. `uv run pytest -v` — expect all tests green.
3. `uv run python -m scraper.main` — live end-to-end dry run. Report matched job count back to me. Show me the matched titles so I can sanity-check the filter.
4. If any title looks like a false positive (e.g., an "Intern" slipped through), add to the seniority reject list and re-run.

## Step 6 — Ship it

1. `git init -b main`, `git add -A`, initial commit.
2. `gh repo create {repo_name} --private --source=. --push`
3. Generate ntfy topic: `NTFY_TOPIC="<prefix>-$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"` — use a short prefix derived from my name. Echo the topic back to me so I can subscribe in the ntfy app.
4. Set secrets (ask me for the Gmail App Password if I enabled email; I can paste it directly):
   ```
   gh secret set NTFY_TOPIC --body "$NTFY_TOPIC"
   gh secret set GMAIL_ADDRESS --body "<my_email>"
   gh secret set GMAIL_APP_PASSWORD --body "<16-char password>"
   ```
5. Send me a test ntfy push so I can confirm my phone is subscribed:
   ```
   curl -d "Setup test" -H "Title: Scraper setup" -H "Tags: white_check_mark" https://ntfy.sh/$NTFY_TOPIC
   ```
6. If email is enabled, run a local smoke test with both channels:
   ```bash
   GMAIL_ADDRESS=... GMAIL_APP_PASSWORD=... NTFY_TOPIC=... uv run python -c "
   from scraper import notify
   notify.notify([{'id':'test:1','company':'TestCo','title':'Test Role','department':'Eng','location':'SF','remote':False,'url':'https://example.com','posted_at':'2026-01-01T00:00:00+00:00'}])
   "
   ```
7. Trigger the first GHA run: `gh workflow run "Scrape Jobs"`, then `gh run watch <id> --exit-status`. Verify green.

## Step 7 — Tell me what's next

Summarize:
- Repo URL
- ntfy topic (for subscribing)
- When the first scheduled run fires
- Any known follow-ups (e.g., Node 20 deprecation warnings in GHA — cosmetic)
- That the state file has been pre-populated with current matches, so the first real cron run will be quiet (only new roles posted after setup will alert).

---

## Notes for the human reading this

- **Nothing in the reference repo is secret.** You're building your own private version with your own secrets.
- **The ntfy topic IS the access credential** — anyone who knows it can read your notifications. Treat like a password, don't commit it.
- **GHA scheduled workflows disable themselves after 60 days of repo inactivity.** The `seen_jobs.json` commit each run keeps the repo active — no keepalive hack needed.
- **Want to add more companies later?** Add another `fetch_<company>()` in `scraper/sources.py` and include it in `fetch_all()`. Ask Claude to do it.
