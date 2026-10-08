#!/usr/bin/env python3
"""Raphael keepalive — cron entrypoints for a fully autonomous dispatch loop.

  keepalive.py dispatch   ensure conductor alive + ping inactive lanes with pending work
                          + wake the integrator when events are pending
  keepalive.py usage      estimate Go spend in rolling 5h/weekly/monthly windows from
                          the router's value-blind usage log; detect provider limit
                          hits; after a hit, probe cheaply until the limit resets, then
                          WAKE THE INTEGRATOR so work continues

Design (user request 2026-10-08):
  - never starts the Raphael live stack, never kills anything except via conductor
  - value-blind: never prints secrets; the Go key is read from .env only to send a
    1-token probe and is never logged
  - idempotent + stateful (state in ~/.raphael-coord), safe to run every 10/20 min
  - budgets are ESTIMATES from our own log (the Go console has no unauthenticated
    usage API); real limit hits are detected from recorded error_code markers

Crontab (appended by integrator, preserves existing entries):
  */10 * * * * python3 .../keepalive.py dispatch  >> ~/.raphael-coord/logs/keepalive.log
  */20 * * * * python3 .../keepalive.py usage     >> ~/.raphael-coord/logs/keepalive-usage.log
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CD = Path(os.environ.get("RAPHAEL_COORD_DIR", Path.home() / ".raphael-coord"))
REPO = Path(__file__).resolve().parents[2]  # repo root derived, no hard-coded home (SEC-1)
USAGE_LOG = REPO / "brain/router/usage.jsonl"
STATE_FILE = CD / "usage-watch.json"
LANES = ["infra", "router", "brain-core", "orb", "voice", "pc-control",
         "computer-use", "qa-security", "tools-memory", "evolution-persona"]

# USD per 1M tokens (input/output) for Go models we actually route. Estimates only —
# used for early-warning; the authoritative signal is a recorded provider limit error.
PRICES = {
    "mimo-v2.5": (0.14, 0.28), "mimo-v2.6": (0.14, 0.28),
    "deepseek-v4-flash": (0.15, 0.60), "deepseek-v4-flash-vision-exp": (0.15, 0.60),
    "deepseek-v4-pro": (0.66, 1.98), "qwen3.7-plus": (0.40, 1.60),
    "default": (0.20, 0.60),
}
DEFAULT_BUDGETS = {"five_h_usd": 12.0, "weekly_usd": 30.0, "monthly_usd": 60.0}


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}", flush=True)


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"budgets": dict(DEFAULT_BUDGETS), "go_hit": None, "warned": {},
            "last_probe": 0.0, "probes_day": {}, "hits": []}


def save_state(st: dict) -> None:
    STATE_FILE.write_text(json.dumps(st, indent=1, ensure_ascii=False))


def read_usage_rows():
    if not USAGE_LOG.exists():
        return []
    rows = []
    try:
        with USAGE_LOG.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue  # damaged tail — skip (value-blind)
    except OSError:
        pass
    return rows


def row_ts(r) -> datetime | None:
    try:
        return datetime.fromisoformat(r.get("timestamp", "")).astimezone(timezone.utc)
    except Exception:
        return None


def cost_usd(r, model_prices: dict | None = None) -> float:
    prices = model_prices or PRICES
    model = str(r.get("model") or "")
    pin, pout = prices.get(model, prices["default"])
    # DeepSeek peak/off-peak is folded into one conservative estimate.
    return ((r.get("tokens_input") or 0) * pin + (r.get("tokens_output") or 0) * pout) / 1_000_000


def window_totals(rows, providers=frozenset({"go", "go_vision"})) -> dict:
    now = datetime.now(timezone.utc)
    wins = {"five_h": now - timedelta(hours=5),
            "weekly": now - timedelta(days=7),
            "monthly": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)}
    out = {k: 0.0 for k in wins}
    limit_hits = []
    for r in rows:
        ts = row_ts(r)
        if ts is None:
            continue
        if r.get("provider") in providers and r.get("outcome") != "failure":
            c = cost_usd(r)
            for k, start in wins.items():
                if ts >= start:
                    out[k] += c
        err = str(r.get("error_code") or "")
        if ("FreeUsageLimit" in err) or ("E_RATE" in err and r.get("provider") in providers):
            # serializable on purpose: state/logs may json-dump this structure
            limit_hits.append({"ts": ts.timestamp(), "ts_iso": ts.isoformat(),
                               "provider": r.get("provider"), "err": err[:80]})
    return {"windows": out, "hits": limit_hits}


def go_key() -> str | None:
    """Read the key from .env for a 1-token availability probe. Value never logged."""
    env = REPO / ".env"
    try:
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith("OPENCODE_API_KEY="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                return val or None
    except OSError:
        return None
    return None


def probe_go_available(timeout: float = 20.0) -> tuple[bool, str]:
    """Tiny real Go chat call. Returns (available, reason). Never prints the key."""
    import urllib.request
    import urllib.error
    key = go_key()
    if not key:
        return False, "no-key"
    body = json.dumps({
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }).encode()
    req = urllib.request.Request(
        "https://opencode.ai/zen/go/v1/chat/completions", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"http-{resp.status}"
    except urllib.error.HTTPError as e:
        raw = b""
        try:
            raw = e.read(400)
        except Exception:
            pass
        text = raw.decode("utf-8", "replace")
        if "FreeUsageLimit" in text or e.code == 429:
            return False, "still-limited"
        # 4xx other than 429/limit means the endpoint accepts us (auth/shape issues
        # are not usage limits) — treat as available for reset detection.
        return e.code not in (401, 403), f"http-{e.code}"
    except Exception as e:  # noqa: BLE001 — network flap, not a limit signal
        return False, f"net-{type(e).__name__}"


# ---------------------------------------------------------------- dispatch
def _run_json(cmd: list[str], timeout: int = 20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return json.loads(r.stdout)
    except Exception:
        return None


def active_sessions() -> set[str]:
    data = _run_json(["opencode", "api", "get", "/session/active"]) or {}
    return set((data.get("data") or {}).keys())


def pending_events(st: dict) -> dict[str, int]:
    cursors = st.get("cursors", {})
    out = {}
    for lane in LANES:
        p = CD / "events" / f"{lane}.jsonl"
        n = sum(1 for _ in p.open()) if p.exists() else 0
        c = int(cursors.get(lane, 0))
        if n > c:
            out[lane] = n - c
    return out


def unread_inbox(lane: str) -> int:
    p = CD / "inbox" / f"{lane}.jsonl"
    if not p.exists():
        return 0
    marker = CD / "inbox" / f"{lane}.read"
    try:
        cur = int(marker.read_text().strip() or "0") if marker.exists() else 0
    except (OSError, ValueError):
        cur = 0
    return max(0, sum(1 for _ in p.open()) - cur)


def ping(lane: str, msg: str) -> bool:
    r = subprocess.run(
        ["python3", str(REPO / "tools/conductor/coord.py"), "ping",
         "--lane", lane, "--msg", msg],
        capture_output=True, text=True, timeout=90)
    ok = r.returncode == 0 and "pinged" in (r.stdout + r.stderr)
    log(f"ping {lane}: {'ok' if ok else 'FAIL ' + (r.stderr or r.stdout)[:120]}")
    return ok


def ensure_conductor(st: dict) -> None:
    if (CD / "STOP").exists():
        return
    pidf = CD / "logs" / "conductor.pid"
    alive = False
    if pidf.exists():
        try:
            os.kill(int(pidf.read_text().strip()), 0)
            alive = True
        except (OSError, ValueError):
            alive = False
    if alive:
        return
    r = subprocess.run(["python3", str(REPO / "tools/conductor/conductor.py"), "start"],
                       capture_output=True, text=True, timeout=60)
    log(f"conductor restart: {(r.stdout or r.stderr)[-160:]}")


def cmd_dispatch() -> int:
    if (CD / "STOP").exists():
        log("STOP armed — dispatch keeper idle")
        return 0
    st = json.loads((CD / "state.json").read_text()) if (CD / "state.json").exists() else {}
    ensure_conductor(st)
    act = active_sessions()
    pend = pending_events(st)
    now = time.time()
    lanes = st.get("lanes", {})
    for lane in LANES:
        meta = lanes.get(lane, {})
        needs = pend.get(lane, 0) > 0 or unread_inbox(lane) > 0
        if not needs or meta.get("paused"):
            continue
        sid = meta.get("session_id")
        if sid and sid in act:
            continue                      # running — it will process its turn
        lp = float(meta.get("last_ping", 0) or 0)
        if now - lp < 300:                # per-lane ping cooldown (cron runs every 10m)
            continue
        ping(lane, (f"coord wake: unread inbox/events waiting — read "
                    f"~/.raphael-coord/inbox/{lane}.jsonl + docs/lanes/{lane}.md Wave-5H "
                    f"section and continue; verify-first, report via coord with a green CI id."))
    # integrator: wake when events pend and my session is idle (cooldown 10m)
    total = sum(pend.values())
    if total > 0 and str(st.get("lanes", {}).get("integrator", {}).get("session_id") or "") not in act:
        lp = float(st.get("integrator_last_ping", 0) or 0)
        if now - lp >= 600:
            if ping("integrator",
                    f"coord wake: {total} unread coord event(s). Handle per "
                    "~/.raphael-coord/prompts/integrator_event.md, then go idle."):
                # NEVER rewrite state.json here: it carries lane cursors and a
                # concurrent full-write reverted all cursors (incident 2026-10-08).
                # The keepalive keeps its own cooldown state.
                own = CD / "keepalive-state.json"
                try:
                    sk = json.loads(own.read_text()) if own.exists() else {}
                except Exception:
                    sk = {}
                sk["integrator_last_ping"] = now
                own.write_text(json.dumps(sk))
    log(f"dispatch check: pending={pend} active={len(act)}")
    return 0


# ---------------------------------------------------------------- usage
def cmd_usage() -> int:
    st = load_state()
    rows = read_usage_rows()
    tot = window_totals(rows)
    wins = tot["windows"]
    budgets = st.get("budgets", DEFAULT_BUDGETS)
    log("usage est USD: five_h={:.4f}/{:.2f} weekly={:.4f}/{:.2f} monthly={:.4f}/{:.2f}".format(
        wins["five_h"], budgets["five_h_usd"], wins["weekly"], budgets["weekly_usd"],
        wins["monthly"], budgets["monthly_usd"]))

    # 1) detect NEW provider limit hits from our own log (authoritative signal)
    last_hit_ts = (st.get("go_hit") or {}).get("ts")
    for h in tot["hits"]:
        ets = h["ts"]
        if last_hit_ts is None or ets > float(last_hit_ts):
            st["go_hit"] = {"ts": ets, "provider": h["provider"], "reason": h["err"]}
            st["hits"].append({"ts": ets, "provider": h["provider"]})
            log(f"LIMIT HIT recorded ({h['provider']}) — watcher will probe hourly and wake on reset")
            _attention(f"Go usage limit hit ({h['provider']}) at {h['ts_iso'][:16]} — "
                       "the cron watcher probes hourly and will auto-wake the integrator when it resets.")
    # 2) early warning at 80% of an estimated window
    for win, key in (("five_h", "five_h"), ("weekly", "weekly"), ("monthly", "monthly")):
        b = budgets.get(f"{key}_usd") or 0
        if b and wins[win] >= b * 0.8 and not st["warned"].get(key):
            st["warned"][key] = wins[win]
            _attention(f"Go usage estimate {win} at {wins[win]:.2f}/{b:.2f} USD (80%+). "
                       "Ease off paid-tier work or raise the budget in usage-watch state.")
        if b and wins[win] < b * 0.6:
            st["warned"].pop(key, None)   # window rolled — allow a fresh warning

    # 3) after a hit: hourly availability probe -> reset -> WAKE integrator
    hit = st.get("go_hit")
    if hit:
        now = time.time()
        if now - float(st.get("last_probe", 0)) >= 3600:
            day = datetime.now(timezone.utc).date().isoformat()
            n = st.get("probes_day", {}).get(day, 0)
            if n < 24:
                ok, reason = probe_go_available()
                st["last_probe"] = now
                st["probes_day"] = {day: n + 1}
                log(f"limit probe: available={ok} ({reason})")
                if ok:
                    st["go_hit"] = None
                    st["probes_day"] = {day: n + 1}
                    _attention("Go usage LIMIT RESET (probe succeeded) — integrator auto-woken.")
                    ping("integrator",
                         "coord wake: Go usage limit RESET detected by the cron watcher — "
                         "resume the coord work loop (handle inbox/events, go idle after).")
    save_state(st)
    return 0


def _attention(msg: str) -> None:
    try:
        subprocess.run(["python3", str(REPO / "tools/conductor/coord.py"),
                        "notify", "--msg", msg], capture_output=True, timeout=30)
    except Exception:
        pass
    log("attention: " + msg)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("dispatch", "usage"):
        print(__doc__)
        return 2
    return cmd_dispatch() if sys.argv[1] == "dispatch" else cmd_usage()


if __name__ == "__main__":
    sys.exit(main())
