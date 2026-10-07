#!/usr/bin/env python3
"""coord — Raphael coordination bus CLI (python3 stdlib only).

File-based message bus shared by every lane worktree + the conductor.
Layout lives in ~/.raphael-coord (override: env RAPHAEL_COORD_DIR).

  events/<lane>.jsonl   append-only, written by that lane (or conductor)
  inbox/<lane>.jsonl    append-only, written by integrator/conductor; <lane>.read = read cursor
  state.json            integrator cursor, wave, lane meta — flock-guarded (state.lock)
  locks/<lane>.lock     long-held activity lock (flock) — headless launches must not collide
  locks/write.lock      short critical section for ALL appends + state writes
  ATTENTION.md          items for the human
  logs/                 conductor + run logs
  STOP                  kill switch (conductor launches nothing while it exists)
  conductor.yaml        conductor config
  prompts/              adoption / continuation / integrator-handler prompts
  bin/coord             symlink to this file

Envelope (one JSON object per line):
  {"ts", "lane", "type", "wave", "ref", "msg", "data"}

Event types (lane -> integrator):  heartbeat task_done wave_done blocked request test_result
                                   error user_attention
Inbox types (integrator -> lane):  decision answer wave_open nudge pause
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

LANES = [
    "router", "brain-core", "pc-control", "voice", "computer-use",
    "orb", "infra", "qa-security", "tools-memory", "evolution-persona",
]
INBOX_LANES = LANES + ["integrator"]
EVENT_TYPES = {
    "heartbeat", "task_done", "wave_done", "blocked", "request",
    "test_result", "error", "user_attention",
}
INBOX_TYPES = {"decision", "answer", "wave_open", "nudge", "pause"}
DEFAULT_WAVE = 2


def coord_dir() -> Path:
    return Path(os.environ.get("RAPHAEL_COORD_DIR") or (Path.home() / ".raphael-coord"))


# ---------------------------------------------------------------- locking / io

@contextlib.contextmanager
def flock(path: Path, blocking: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(fd, flags)
        except BlockingIOError:
            os.close(fd)
            raise
        yield fd
    finally:
        with contextlib.suppress(Exception):
            fcntl.flock(fd, fcntl.LOCK_UN)
        with contextlib.suppress(Exception):
            os.close(fd)


def write_lock(cd: Path):
    return flock(cd / "locks" / "write.lock")


def append_jsonl(path: Path, obj: dict, cd: Path) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with flock(cd / "locks" / "write.lock"):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode())
            os.fsync(fd)
        finally:
            os.close(fd)


def read_jsonl(path: Path) -> list:
    out = []
    if not path.exists():
        return out
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            print(f"coord: WARNING: corrupt line {n} in {path}", file=sys.stderr)
    return out


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as f:
        return sum(1 for _ in f)


def default_state() -> dict:
    lanes = {}
    for ln in LANES:
        lanes[ln] = {
            "status": "waiting", "heartbeat": None, "last_event_type": None,
            "session_id": None, "branch_head": None, "paused": False,
            "failures": 0, "backoff_until": None, "last_ping": None,
            "wave_role": "standby", "merged_wave": None,
        }
    return {
        "version": 1,
        "current_wave": DEFAULT_WAVE,
        "conductor_seen_wave": DEFAULT_WAVE,
        "updated": time.time(),
        "cursors": {ln: 0 for ln in LANES},
        "lanes": lanes,
        "wave_launches": {},
        "start_conditions": {"tools-memory": {"min_wave": 3},
                             "evolution-persona": {"min_wave": 4}},
        "integrator_pending_since": None,
        "last_wake_signature": None,
        "wake_misses": 0,
    }


def _read_state_unlocked(cd: Path) -> dict:
    """Read state.json WITHOUT taking state.lock — caller must already hold it
    (flock is per-open-file-description: re-locking the same file from the same
    process on a new fd blocks forever)."""
    p = cd / "state.json"
    st = default_state()
    if p.exists():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        for k, v in loaded.items():
            if k == "lanes":
                for ln, meta in v.items():
                    st["lanes"].setdefault(ln, {}).update(meta)
            else:
                st[k] = v
    return st


def read_state(cd: Path) -> dict:
    with flock(cd / "locks" / "state.lock"):
        return _read_state_unlocked(cd)


def write_state(cd: Path, state: dict) -> None:
    state["updated"] = time.time()
    p = cd / "state.json"
    with flock(cd / "locks" / "state.lock"):
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)


def mutate_state(cd: Path, fn) -> object:
    with flock(cd / "locks" / "state.lock"):
        st = _read_state_unlocked(cd)
        ret = fn(st)
        st["updated"] = time.time()
        p = cd / "state.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        return ret


def conductor_running(cd: Path) -> int | None:
    pidfile = cd / "logs" / "conductor.pid"
    if not pidfile.exists():
        return None
    try:
        pid = int(pidfile.read_text().strip())
    except (ValueError, OSError):
        return None
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return None
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        return None
    return pid if "conductor" in cmd else None


def envelope(lane: str, etype: str, msg: str, ref, data, wave: int | None = None) -> dict:
    if wave is None:
        wave = read_state(coord_dir())["current_wave"]
    return {
        "ts": round(time.time(), 3), "lane": lane, "type": etype,
        "wave": wave,
        "ref": ref, "msg": msg, "data": data,
    }


# ---------------------------------------------------------------- notify

def do_notify(text: str, append_attention: bool = True) -> None:
    cd = coord_dir()
    if os.environ.get("COORD_NO_TOAST") != "1":
        try:
            b64 = base64.b64encode(text.encode()).decode()
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                "ContentType = WindowsRuntime] | Out-Null;"
                "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null;"
                "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
                "[Windows.UI.Notifications.ToastTemplateType]::ToastText01);"
                "$n = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:COORD_TOAST_B64));"
                "$t.GetElementsByTagName('text').Item(0).AppendChild($t.CreateTextNode($n)) | Out-Null;"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier().Show("
                "[Windows.UI.Notifications.ToastNotification]::new($t))"
            )
            env = dict(os.environ, COORD_TOAST_B64=b64)
            r = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                env=env, capture_output=True, timeout=20,
            )
            if r.returncode == 0:
                return
        except Exception:
            pass
    # fallback: terminal bell (+ ATTENTION.md unless caller already wrote it)
    sys.stdout.write("\a")
    sys.stdout.flush()
    if append_attention:
        with (cd / "ATTENTION.md").open("a", encoding="utf-8") as f:
            f.write(f"- [{time.strftime('%Y-%m-%d %H:%M:%S')}] notify: {text}\n")


# ---------------------------------------------------------------- commands

def cmd_init(args) -> int:
    cd = coord_dir()
    for sub in ("bin", "events", "inbox", "locks", "logs", "prompts"):
        (cd / sub).mkdir(parents=True, exist_ok=True)
    st = cd / "state.json"
    if not st.exists():
        write_state(cd, default_state())
    att = cd / "ATTENTION.md"
    if not att.exists():
        att.write_text("# ATTENTION — items for the human\n\n(nothing pending)\n", encoding="utf-8")
    # this file as the shared CLI
    me = Path(__file__).resolve()
    link = cd / "bin" / "coord"
    if link.is_symlink() or link.exists():
        if not (link.is_symlink() and link.resolve() == me):
            link.unlink()
            link.symlink_to(me)
    else:
        link.symlink_to(me)
    link.chmod(0o755) if link.exists() else None
    # refresh protocol + prompts from the repo copies (repo = source of truth)
    src = me.parent  # tools/conductor
    repo_doc = src.parents[1] / "docs" / "COORD_PROTOCOL.md"
    if repo_doc.exists():
        (cd / "PROTOCOL.md").write_text(repo_doc.read_text(encoding="utf-8"), encoding="utf-8")
    if (src / "prompts").is_dir():
        for p in (src / "prompts").iterdir():
            if p.is_file():
                (cd / "prompts" / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    cfg = cd / "conductor.yaml"
    if not cfg.exists() and (src / "conductor.yaml").exists():
        cfg.write_text((src / "conductor.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    for ln in LANES:
        for name in (f"events/{ln}.jsonl", f"inbox/{ln}.jsonl"):
            (cd / name).touch()
    (cd / "inbox" / "integrator.jsonl").touch()
    print(f"coord: initialized {cd}")
    return 0


def cmd_post(args) -> int:
    if args.lane not in LANES:
        sys.exit(f"coord: unknown lane {args.lane!r} (events are lane-scoped)")
    if args.type not in EVENT_TYPES:
        sys.exit(f"coord: bad type {args.type!r}; one of {sorted(EVENT_TYPES)}")
    if isinstance(args.data, str):
        data = json.loads(args.data) if args.data else None
    else:
        data = args.data
    cd = coord_dir()
    obj = envelope(args.lane, args.type, args.msg, args.ref, data)
    if args.type == "heartbeat" and isinstance(data, dict) and data.get("session_id"):
        sid = data["session_id"]

        def _reg(st):
            st["lanes"].setdefault(args.lane, {})["session_id"] = sid
        mutate_state(cd, _reg)
    append_jsonl(cd / "events" / f"{args.lane}.jsonl", obj, cd)
    print(f"coord: posted {args.type} -> events/{args.lane}.jsonl")
    return 0


def cmd_reply(args) -> int:
    if args.lane not in INBOX_LANES:
        sys.exit(f"coord: unknown inbox {args.lane!r}")
    if args.type not in INBOX_TYPES:
        sys.exit(f"coord: bad type {args.type!r}; one of {sorted(INBOX_TYPES)}")
    if isinstance(args.data, str):
        data = json.loads(args.data) if args.data else None
    else:
        data = args.data
    cd = coord_dir()
    append_jsonl(cd / "inbox" / f"{args.lane}.jsonl",
                 envelope(args.lane, args.type, args.msg, args.ref, data), cd)
    print(f"coord: replied {args.type} -> inbox/{args.lane}.jsonl")
    return 0


def _read_cursor(cd: Path, lane: str) -> int:
    p = cd / "inbox" / f"{lane}.read"
    try:
        return int(p.read_text().strip() or "0")
    except (OSError, ValueError):
        return 0


def cmd_inbox(args) -> int:
    if args.lane not in INBOX_LANES:
        sys.exit(f"coord: unknown inbox {args.lane!r}")
    cd = coord_dir()
    items = read_jsonl(cd / "inbox" / f"{args.lane}.jsonl")
    cur = _read_cursor(cd, args.lane)
    shown = items[cur:] if args.unread else items
    if args.json:
        print(json.dumps(shown, ensure_ascii=False, indent=1))
    else:
        for i, m in enumerate(shown):
            n = (cur if args.unread else 0) + i + 1
            print(f"[{n}] {m['ts']:.0f} {m['type']:9s} {m['msg']}")
    if args.mark_read:
        with flock(cd / "locks" / "write.lock"):
            (cd / "inbox" / f"{args.lane}.read").write_text(str(len(items)))
    return 0


def cmd_status(args) -> int:
    cd = coord_dir()
    st = read_state(cd)
    pid = conductor_running(cd)
    lanes_out = {}
    pend_total = 0
    for ln in LANES:
        ev_n = line_count(cd / "events" / f"{ln}.jsonl")
        pend = max(0, ev_n - st["cursors"].get(ln, 0))
        pend_total += pend
        inbox_n = line_count(cd / "inbox" / f"{ln}.jsonl")
        inbox_unread = max(0, inbox_n - _read_cursor(cd, ln))
        meta = st["lanes"].get(ln, {})
        # lock probe: can WE take it exclusively? failure = someone holds it
        held = False
        try:
            fd = os.open(cd / "locks" / f"{ln}.lock", os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
            except BlockingIOError:
                held = True
            finally:
                os.close(fd)
        except OSError:
            pass
        hb = meta.get("heartbeat")
        lanes_out[ln] = {
            "status": "paused" if meta.get("paused") else ("lock-held" if held else meta.get("status", "waiting")),
            "heartbeat_age_s": (round(time.time() - hb) if hb else None),
            "pending_events": pend,
            "inbox_unread": inbox_unread,
            "session_id": meta.get("session_id"),
            "branch_head": meta.get("branch_head"),
            "failures": meta.get("failures", 0),
            "wave_role": meta.get("wave_role"),
        }
    integrator_inbox = line_count(cd / "inbox" / "integrator.jsonl")
    out = {
        "wave": st["current_wave"],
        "conductor": {"running": bool(pid), "pid": pid},
        "lanes": lanes_out,
        "pending_events_total": pend_total,
        "integrator_inbox_lines": integrator_inbox,
        "stop_file": (cd / "STOP").exists(),
        "attention_open": _attention_count(cd),
    }
    if args.json:
        print(json.dumps(out, indent=1))
    else:
        print(f"wave={out['wave']}  conductor={'running pid=' + str(pid) if pid else 'STOPPED'}  "
              f"pending_events={pend_total}  STOP={'yes' if out['stop_file'] else 'no'}")
        for ln, m in lanes_out.items():
            hb = f"hb {m['heartbeat_age_s']}s ago" if m["heartbeat_age_s"] is not None else "no-hb"
            print(f"  {ln:18s} {m['status']:10s} {hb:14s} ev+{m['pending_events']} "
                  f"inbox+{m['inbox_unread']} {'PAUSED' if m['status']=='paused' else ''}")
    return 0


def _attention_count(cd: Path) -> int:
    p = cd / "ATTENTION.md"
    return p.read_text(encoding="utf-8").count("\n- [") if p.exists() else 0


def cmd_wave(args) -> int:
    print(read_state(coord_dir())["current_wave"])
    return 0


def cmd_wave_bump(args) -> int:
    cd = coord_dir()

    def _b(st):
        st["current_wave"] = args.wave
        for ln in LANES:
            st["lanes"].setdefault(ln, {}).update(
                {"merged_wave": None, "status": "waiting",
                 "wave_role": "standby"})
    mutate_state(cd, _b)
    print(f"coord: current_wave -> {args.wave}")
    return 0


def cmd_mode(args) -> int:
    cd = coord_dir()
    st = read_state(cd)
    lane_ok = args.lane in INBOX_LANES
    if not lane_ok:
        sys.exit(f"coord: unknown lane {args.lane!r}")
    running = conductor_running(cd) is not None
    paused = st["lanes"].get(args.lane, {}).get("paused", False)
    if running and not (cd / "STOP").exists() and not paused:
        print("exit")
    else:
        print("wait")
    return 0


def cmd_wait(args) -> int:
    cd = coord_dir()
    t0 = time.time()
    if args.for_ == "wave":
        start = read_state(cd)["current_wave"]
        while time.time() - t0 < args.timeout:
            if read_state(cd)["current_wave"] != start:
                return 0
            time.sleep(0.5)
        return 1
    else:  # inbox
        if args.lane not in INBOX_LANES:
            sys.exit(f"coord: unknown inbox {args.lane!r}")
        start = line_count(cd / "inbox" / f"{args.lane}.jsonl") - _read_cursor(cd, args.lane)
        while time.time() - t0 < args.timeout:
            now = line_count(cd / "inbox" / f"{args.lane}.jsonl") - _read_cursor(cd, args.lane)
            if now > start:
                return 0
            time.sleep(0.5)
        return 1


def cmd_attention(args) -> int:
    cd = coord_dir()
    with (cd / "ATTENTION.md").open("a", encoding="utf-8") as f:
        f.write(f"- [{time.strftime('%Y-%m-%d %H:%M:%S')}] {args.text}\n")
    do_notify(f"RAPHAEL attention: {args.text}", append_attention=False)
    print("coord: attention recorded")
    return 0


def cmd_notify(args) -> int:
    do_notify(args.text)
    print("coord: notified")
    return 0


def cmd_cursor(args) -> int:
    if args.lane not in LANES:
        sys.exit(f"coord: unknown lane {args.lane!r}")
    cd = coord_dir()
    n = args.set if args.set is not None else line_count(cd / "events" / f"{args.lane}.jsonl")

    def _c(st):
        st["cursors"][args.lane] = n
    mutate_state(cd, _c)
    print(f"coord: cursor {args.lane} -> {n}")
    return 0


# ---- session ping (the no-token-wait mechanism; see .opencode/research/session-ping-delegation.md)

def find_session(cd: Path, lane: str, st: dict | None = None) -> str | None:
    st = st if st is not None else read_state(cd)
    sid = st["lanes"].get(lane, {}).get("session_id")
    if sid:
        return sid
    # fallback: discover by worktree directory (rename-proof — titles are user-owned).
    # Multiple sessions can share a directory (history) — prefer RUNNING, else first
    # (the API returns newest first).
    try:
        r = subprocess.run(
            ["opencode", "api", "get", "/api/session?limit=200"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(r.stdout).get("data", [])
        active_ids = set()
        with contextlib.suppress(Exception):
            ra = subprocess.run(
                ["opencode", "api", "get", "/api/session/active"],
                capture_output=True, text=True, timeout=30,
            )
            active_ids = set(json.loads(ra.stdout).get("data", {}))
        want = f"/raphael-wt/{lane}" if lane in LANES else "/raphael"
        match = None
        for s in data if isinstance(data, list) else []:
            d = ((s.get("location") or {}).get("directory") or "")
            if d.rstrip("/").endswith(want.rstrip("/")) or (lane == "integrator" and d == "/home/dami/raphael"):
                if match is None:
                    match = s.get("id")
                if s.get("id") in active_ids:
                    match = s.get("id")
                    break
        if match:
            st["lanes"].setdefault(lane, {})["session_id"] = match
            return match
    except Exception as e:
        print(f"coord: session discovery failed: {e}", file=sys.stderr)
    return None


def cmd_ping(args) -> int:
    cd = coord_dir()
    sid = find_session(cd, args.lane)
    if not sid:
        sys.exit(f"coord: no session for lane {args.lane!r} (register it or let the lane heartbeat)")
    payload = json.dumps({"text": args.msg, "delivery": args.delivery})
    r = subprocess.run(
        ["opencode", "api", "post", f"/api/session/{sid}/prompt", "--data", payload],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode == 0 and '"data"' in r.stdout:
        print(f"coord: pinged {args.lane} ({sid})")
        return 0
    if args.delivery == "steer":  # busy/conflict -> queue explicitly, then give up
        payload = json.dumps({"text": args.msg, "delivery": "queue"})
        r2 = subprocess.run(
            ["opencode", "api", "post", f"/api/session/{sid}/prompt", "--data", payload],
            capture_output=True, text=True, timeout=60,
        )
        if r2.returncode == 0 and '"data"' in r2.stdout:
            print(f"coord: pinged {args.lane} ({sid}) [queued]")
            return 0
    print(f"coord: ping FAILED for {args.lane}: {(r.stderr or r.stdout)[:300]}", file=sys.stderr)
    return 1


def cmd_session_register(args) -> int:
    cd = coord_dir()

    def _r(st):
        st["lanes"].setdefault(args.lane, {})["session_id"] = args.session_id
    mutate_state(cd, _r)
    print(f"coord: {args.lane} -> {args.session_id}")
    return 0


def cmd_sessions(args) -> int:
    cd = coord_dir()
    try:
        r = subprocess.run(["opencode", "api", "get", "/api/session?limit=200"],
                           capture_output=True, text=True, timeout=30)
        data = json.loads(r.stdout).get("data", [])
        active = json.loads(subprocess.run(
            ["opencode", "api", "get", "/api/session/active"],
            capture_output=True, text=True, timeout=30).stdout).get("data", {})
    except Exception as e:
        print(f"coord: cannot query sessions: {e}", file=sys.stderr)
        return 1
    rows = []
    for s in data if isinstance(data, list) else []:
        d = ((s.get("location") or {}).get("directory") or "").rstrip("/")
        lane = None
        if d == "/home/dami/raphael":
            lane = "integrator"
        elif "/raphael-wt/" in d:
            lane = d.rsplit("/", 1)[-1]
        if lane:
            rows.append((lane, s.get("id"), s.get("title", ""),
                         "RUNNING" if s.get("id") in active else "idle"))
    rows.sort()
    if args.json:
        print(json.dumps([{"lane": a, "session": b, "title": c, "state": d}
                          for a, b, c, d in rows], indent=1, ensure_ascii=False))
    else:
        for lane, sid, title, state in rows:
            print(f"  {lane:18s} {state:8s} {sid}  {title}")
    return 0


# ---- activity lock (lane holds its worktree lock for its session lifetime)

def cmd_hold(args) -> int:
    cd = coord_dir()
    lockp = cd / "locks" / f"{args.lane}.lock"
    pidp = cd / "locks" / f"{args.lane}.pid"
    if pidp.exists():
        try:
            os.kill(int(pidp.read_text().strip()), 0)
            print(f"coord: {args.lane} already held")
            return 0
        except (ValueError, ProcessLookupError):
            pass
    me = Path(__file__).resolve()
    subprocess.Popen(
        [sys.executable, str(me), "_hold", "--lane", args.lane],
        start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)
    print(f"coord: holding {args.lane}")
    return 0


def cmd_hold_inner(args) -> int:
    cd = coord_dir()
    lockp = cd / "locks" / f"{args.lane}.lock"
    pidp = cd / "locks" / f"{args.lane}.pid"
    lockp.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lockp, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)  # blocks until held
    pidp.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    try:
        while True:
            time.sleep(30)
    finally:
        with contextlib.suppress(Exception):
            pidp.unlink()
        os.close(fd)
    return 0


def cmd_release(args) -> int:
    cd = coord_dir()
    pidp = cd / "locks" / f"{args.lane}.pid"
    if pidp.exists():
        try:
            os.kill(int(pidp.read_text().strip()), signal.SIGTERM)
            print(f"coord: released {args.lane}")
        except (ValueError, ProcessLookupError):
            print(f"coord: stale pid file cleaned for {args.lane}")
        with contextlib.suppress(Exception):
            pidp.unlink()
    else:
        print(f"coord: {args.lane} not held")
    return 0


# ---------------------------------------------------------------- arg parsing

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="coord", description="Raphael coordination bus")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create/refresh ~/.raphael-coord layout")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("post", help="append an event to events/<lane>.jsonl")
    s.add_argument("--lane", required=True)
    s.add_argument("--type", required=True)
    s.add_argument("--msg", required=True)
    s.add_argument("--ref")
    s.add_argument("--data", help="JSON object")
    s.set_defaults(fn=cmd_post)

    s = sub.add_parser("reply", help="append to inbox/<lane>.jsonl (integrator/conductor)")
    s.add_argument("--lane", required=True)
    s.add_argument("--type", required=True)
    s.add_argument("--msg", required=True)
    s.add_argument("--ref")
    s.add_argument("--data", help="JSON object")
    s.set_defaults(fn=cmd_reply)

    s = sub.add_parser("inbox", help="read an inbox")
    s.add_argument("--lane", required=True)
    s.add_argument("--unread", action="store_true")
    s.add_argument("--mark-read", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_inbox)

    s = sub.add_parser("status", help="bus status")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("wave", help="print current_wave")
    s.set_defaults(fn=cmd_wave)

    s = sub.add_parser("wave-bump", help="set current_wave (integrator handler)")
    s.add_argument("--wave", type=int, required=True)
    s.set_defaults(fn=cmd_wave_bump)

    s = sub.add_parser("mode", help='print "exit" (you will be pinged) or "wait"')
    s.add_argument("--lane", required=True)
    s.set_defaults(fn=cmd_mode)

    s = sub.add_parser("wait", help="block until wave changes or inbox grows")
    s.add_argument("--lane", required=True)
    s.add_argument("--for", dest="for_", choices=["wave", "inbox"], required=True)
    s.add_argument("--timeout", type=float, default=90)
    s.set_defaults(fn=cmd_wait)

    s = sub.add_parser("attention", help="record an item for the human + notify")
    s.add_argument("text")
    s.set_defaults(fn=cmd_attention)

    s = sub.add_parser("notify", help="Windows toast (fallback: bell + ATTENTION.md)")
    s.add_argument("text")
    s.set_defaults(fn=cmd_notify)

    s = sub.add_parser("cursor", help="advance the integrator's event cursor for a lane")
    s.add_argument("--lane", required=True)
    s.add_argument("--set", type=int)
    s.set_defaults(fn=cmd_cursor)

    s = sub.add_parser("ping", help="wake a lane's session via API prompt injection")
    s.add_argument("--lane", required=True)
    s.add_argument("--msg", required=True)
    s.add_argument("--delivery", choices=["steer", "queue"], default="steer")
    s.set_defaults(fn=cmd_ping)

    s = sub.add_parser("session-register", help="record lane -> session id in state.json")
    s.add_argument("--lane", required=True)
    s.add_argument("--session-id", required=True)
    s.set_defaults(fn=cmd_session_register)

    s = sub.add_parser("sessions", help="list detected sessions mapped to lanes")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_sessions)

    s = sub.add_parser("hold", help="take the lane activity lock (session lifetime)")
    s.add_argument("--lane", required=True)
    s.set_defaults(fn=cmd_hold)

    s = sub.add_parser("release", help="release the lane activity lock")
    s.add_argument("--lane", required=True)
    s.set_defaults(fn=cmd_release)

    s = sub.add_parser("_hold", help="internal hold daemon")
    s.add_argument("--lane", required=True)
    s.set_defaults(fn=cmd_hold_inner)

    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
