"""State management for seen jobs — load, save, diff, update."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

STATE_PATH = Path("seen_jobs.json")


def load(path: Path = STATE_PATH) -> dict[str, str]:
    """Load seen_jobs.json; return {} if file missing or empty."""
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not raw.strip():
        return {}
    return json.loads(raw)


def save(seen: dict[str, str], path: Path = STATE_PATH) -> None:
    """Atomic write (write tmp + os.replace). Pretty-printed, sorted keys, trailing newline."""
    path = Path(path)
    parent = path.parent if str(path.parent) else Path(".")
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(seen, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def diff(current_jobs: list[dict], seen: dict[str, str]) -> list[dict]:
    """Return jobs whose `id` is not in `seen`. Preserve input order."""
    return [job for job in current_jobs if job["id"] not in seen]


def update(
    seen: dict[str, str], new_jobs: list[dict], now_iso: str
) -> dict[str, str]:
    """Return a new dict with new_jobs' ids added mapped to now_iso. Don't mutate input."""
    merged = dict(seen)
    for job in new_jobs:
        jid = job["id"]
        if jid not in merged:
            merged[jid] = now_iso
    return merged
