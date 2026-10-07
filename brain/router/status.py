"""Usage / rate tracking for `GET /status` (Wave 3 lane goal).

`brain.router.usage_status()` (async, no network) aggregates the recent
`brain/router/usage.jsonl` events with the LIVE limiter/breaker state, so
brain-core can surface router health in `/status` with one dict:

    {"window": {...}, "calls": {...}, "tokens": {...}, "by_provider": {...},
     "by_purpose": {...", "errors": {...}, "providers": {...}, "vision_paid": {...}}

Rules: no secrets (usage.jsonl has none), no image data, bounded read (tail of
the file), and it NEVER raises — `/status` must stay up even if the log is
missing/corrupt.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

# keep /status cheap: only the tail of the log is ever read
TAIL_LINES = 2000
WINDOW_HOURS = 24


def read_usage_events(path: Path,
                      since: datetime | None = None,
                      tail: int = TAIL_LINES) -> list[dict[str, Any]]:
    """Parse the usage log tail, keeping events at/after `since` (UTC).

    Never raises: a missing or corrupt file is simply an empty window.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not raw.strip():
        return []
    lines = raw.splitlines()[-tail:]
    cutoff = since or (datetime.now(timezone.utc)
                       - timedelta(hours=WINDOW_HOURS))
    events: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        ts = ev.get("timestamp")
        if isinstance(ts, str):
            try:
                when = datetime.fromisoformat(ts)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                if when < cutoff:
                    continue
            except ValueError:
                pass  # unparseable timestamp → count it (better loud than lost)
        events.append(ev)
    return events


def summarize_events(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate usage events into the `/status` shape (pure, tested)."""
    calls: dict[str, int] = {"total": 0, "ok": 0, "errors": 0}
    tokens = {"input": 0, "output": 0}
    by_provider: dict[str, dict[str, int]] = {}
    by_purpose: dict[str, dict[str, int]] = {}
    errors: dict[str, int] = {}

    for ev in events:
        calls["total"] += 1
        ok = str(ev.get("outcome") or "") == "success"
        calls["ok" if ok else "errors"] += 1

        provider = str(ev.get("provider") or "unknown")
        bucket = by_provider.setdefault(
            provider, {"calls": 0, "errors": 0, "input": 0, "output": 0})
        bucket["calls"] += 1
        if not ok:
            bucket["errors"] += 1
        tin = int(ev.get("tokens_input") or 0)
        tout = int(ev.get("tokens_output") or 0)
        bucket["input"] += tin
        bucket["output"] += tout
        tokens["input"] += tin
        tokens["output"] += tout

        purpose = str(ev.get("task_kind") or "unspecified")
        pbucket = by_purpose.setdefault(
            purpose, {"calls": 0, "errors": 0, "input": 0, "output": 0})
        pbucket["calls"] += 1
        if not ok:
            pbucket["errors"] += 1
        pbucket["input"] += tin
        pbucket["output"] += tout

        code = ev.get("error_code")
        if code:
            errors[str(code)] = errors.get(str(code), 0) + 1

    return {
        "calls": calls,
        "tokens": tokens,
        "by_provider": dict(sorted(by_provider.items())),
        "by_purpose": dict(sorted(by_purpose.items())),
        "errors": dict(sorted(errors.items(), key=lambda kv: (-kv[1], kv[0]))),
    }
