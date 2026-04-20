"""Orchestrator: scrape → filter → diff → notify → persist."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from scraper import filters, notify, sources, state

log = logging.getLogger("scraper")


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    fetched = sources.fetch_all()
    log.info("fetched %d jobs total", len(fetched))

    matched = [j for j in fetched if filters.matches(j)]
    log.info("matched %d jobs after filtering", len(matched))

    seen = state.load()
    new_jobs = state.diff(matched, seen)
    log.info("new jobs since last run: %d", len(new_jobs))

    if new_jobs:
        channels = notify.notify(new_jobs)
        log.info("notified via: %s", channels or "<none>")

    now_iso = datetime.now(timezone.utc).isoformat()
    state.save(state.update(seen, new_jobs, now_iso))
    return 0


if __name__ == "__main__":
    sys.exit(run())
