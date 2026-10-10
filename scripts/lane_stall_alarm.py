#!/usr/bin/env python3
"""Lane stall alarm (Wave 5U, owner request): re-ping an active lane that has
gone quiet.

Heuristic: for each lane, compare the mtime of MY last message to their inbox
(`.raphael-coord/inbox/<lane>.jsonl`) against their newest event ts
(`.raphael-coord/events/<lane>.jsonl`). If I pinged them and they have produced
NO event for > STALL_S, they are stalled -> `coord ping` a nudge (rate-limited:
at most one nudge per lane per STALL_S, tracked in a state file).

A lane that is intentionally WAIT never trips this: their last event (a
heartbeat/ack) is newer than my last ping, or both are recent. Only a ping
that is answered by silence for 30 min fires.

Run from cron every 10 min. Never raises (best-effort); logs one line per nudge.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

STALL_S = int(os.environ.get("STALL_S", "1800"))          # 30 min quiet = stalled
COORD = Path(os.path.expanduser("~/.raphael-coord"))
EVENTS = COORD / "events"
INBOX = COORD / "inbox"
STATE = COORD / "stall-state.json"                        # last nudge ts per lane
COORD_BIN = Path(os.path.expanduser("~/.raphael-coord/bin/coord"))
LOG = Path("/tmp/lane-stall-alarm.log")


def log(msg: str) -> None:
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with LOG.open("a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    print(line)


def newest_event_ts(lane: str) -> float:
    f = EVENTS / ("%s.jsonl" % lane)
    if not f.exists():
        return 0.0
    last = 0.0
    try:
        for ln in f.read_text().splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                last = max(last, float(json.loads(ln).get("ts", 0.0)))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    except OSError:
        return 0.0
    return last


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(st: dict) -> None:
    try:
        STATE.write_text(json.dumps(st, indent=1))
    except OSError:
        pass


def load_active() -> set:
    """Lanes currently expected to be working. Maintained by the integrator on
    each wave dispatch. Lanes not in this set (WAIT / paused / burst-later) are
    never nudged. 'integrator' is always excluded (that's me)."""
    f = COORD / "active-lanes.json"
    try:
        active = set(json.loads(f.read_text()))
    except (OSError, json.JSONDecodeError):
        return set()
    active.discard("integrator")
    return active


def main() -> int:
    st = load_state()
    now = time.time()
    active = load_active()
    if not active:
        log("ok: no active lanes declared (active-lanes.json empty/missing) — 0 nudged")
        return 0
    lanes = set(active)
    nudged = 0
    for lane in sorted(lanes):
        inbox = INBOX / ("%s.jsonl" % lane)
        if not inbox.exists():
            continue                                   # never pinged -> not active
        try:
            last_ping = inbox.stat().st_mtime
        except OSError:
            continue
        ev = newest_event_ts(lane)
        quiet = now - max(ev, last_ping)               # seconds since any activity
        # stalled: my last ping is the most recent thing and it's > STALL_S old
        last_nudge = float(st.get(lane, 0.0))
        if last_ping >= ev and quiet > STALL_S and (now - last_nudge) > STALL_S:
            msg = ("stall alarm: no response %.0f min after your last ping — "
                   "please ack status or wave_done (or reply WAIT if idle)."
                   % (quiet / 60.0))
            try:
                subprocess.run([str(COORD_BIN), "ping", "--lane", lane,
                                "--msg", msg], check=False, capture_output=True,
                               timeout=30)
                st[lane] = now
                nudged += 1
                log("NUDGE %s (quiet %.0f min)" % (lane, quiet / 60.0))
            except (OSError, subprocess.SubprocessError) as exc:
                log("nudge failed for %s: %s" % (lane, exc))
    if nudged == 0:
        log("ok: %d lane(s) checked, 0 stalled" % len(lanes))
    save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
