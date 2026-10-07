#!/usr/bin/env python3
"""conductor — Raphael's non-LLM watcher/launcher (python3 stdlib only, runs in tmux).

Loop every tick (default 15 s):
  a) STOP kill switch          — STOP file => launch nothing, SIGTERM managed children, exit 0
  b) wake the integrator       — unread events, debounced 60-90 s, FRESH headless `opencode run`,
                                 skipped while a run is active; loop guard if cursor not advancing
  c) wave open                 — current_wave increased => inbox wave_open + wake eligible lanes:
                                 PING their existing session (POST /api/session/{sid}/prompt);
                                 headless fallback ONLY when no session exists and lane lock free
  d) concurrency cap           — max_parallel_runs (default 3); priority integrator > infra/
                                 router/brain-core > rest; queue the remainder
  e) safety                    — per-run timeout, consecutive-failure limit -> pause + attention,
                                 runs-per-hour cap, exponential backoff on 429/rate errors
  f) stall detection           — session running per API but heartbeat stale > 20 min -> attention.
                                 NEVER kills interactive sessions; only reaps children it spawned
  g) lane locks respected      — never headless-launch into a worktree whose lock is held
  h) logging                   — every launch/exit + duration -> logs/runs.jsonl, logs/conductor.log

Commands: conductor start|stop|status|pause <lane>|resume <lane>|loop
Config:   ~/.raphael-coord/conductor.yaml (JSON syntax, valid YAML 1.2 — json.load, stdlib only)

Lock discipline: state.json is read and written in SEPARATE short flocked sections; never
nested (flock is per-open-file-description — same-process re-lock blocks forever). All
subprocess work happens outside the state lock.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coord  # noqa: E402
from coord import (  # noqa: E402
    LANES, append_jsonl, coord_dir, flock, line_count, read_jsonl, read_state,
    write_state,
)

TMUX_SESSION = "raphael-conductor"


def now() -> float:
    return time.time()


class Conductor:
    def __init__(self, cfg: dict, dry_run: bool, tick: float | None):
        self.cd = coord_dir()
        self.cfg = cfg
        self.dry = bool(dry_run or cfg.get("dry_run"))
        self.tick = float(tick or cfg.get("tick_s", 15))
        self.children: dict[int, dict] = {}      # pid -> meta (headless/integrator runs)
        self.dry_active: set[str] = set()        # dry-run: synthetic "running" lanes for the cap
        self.held_locks: dict[str, int] = {}     # lane -> fd held while its child runs
        self.pending_since: float | None = None
        self.stall_notified: dict[str, float] = {}
        self.stop = False
        self.log_path = self.cd / "logs" / "conductor.log"
        self.runs_path = self.cd / "logs" / "runs.jsonl"
        self.dry_path = self.cd / "logs" / "launches.dryrun.jsonl"
        self.kids_path = self.cd / "logs" / "conductor.children.json"

    # ------------------------------------------------------------ logging
    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line, flush=True)
        self.cd.joinpath("logs").mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def attention(self, msg: str) -> None:
        self.log(f"ATTENTION: {msg}")
        with (self.cd / "ATTENTION.md").open("a", encoding="utf-8") as f:
            f.write(f"- [{time.strftime('%Y-%m-%d %H:%M:%S')}] conductor: {msg}\n")
        with contextlib.suppress(Exception):
            subprocess.run([sys.executable, str(Path(coord.__file__)), "notify",
                            f"RAPHAEL conductor: {msg}"],
                           env={**os.environ,
                                "COORD_NOTIFY_NO_APPEND": "1",
                                "COORD_NO_TOAST": os.environ.get("COORD_NO_TOAST", "0")},
                           capture_output=True, timeout=30)

    def _save_children(self) -> None:
        with contextlib.suppress(OSError):
            self.kids_path.write_text(json.dumps(
                {str(p): {k: v for k, v in m.items() if k != "proc"}
                 for p, m in self.children.items()}, indent=1))

    # ------------------------------------------------------------ config helpers
    def min_wave(self, lane: str) -> int:
        return int(self.cfg.get("start_conditions", {}).get(lane, {}).get("min_wave", 1))

    def priority(self) -> list:
        pri = self.cfg.get("priority", LANES)
        ordered = [l for l in pri if l in LANES]
        return ordered + [l for l in LANES if l not in ordered]

    def fmt(self, cmd_key: str, lane: str) -> list:
        prompt = self.cfg.get("integrator_prompt" if lane == "integrator" else "lane_prompt",
                              "prompts/lane_continue.md")
        pp = Path(prompt)
        if not pp.is_absolute():
            pp = self.cd / prompt          # resolve relative prompts against the coord dir
        return [c.format(lane=lane, model=self.cfg.get("model", ""), prompt=str(pp))
                for c in self.cfg.get(cmd_key)]

    # ------------------------------------------------------------ accounting
    def runs_last_hour(self) -> int:
        if not self.runs_path.exists():
            return 0
        cutoff = now() - 3600
        return sum(1 for r in read_jsonl(self.runs_path)
                   if r.get("kind") not in (None,) and r.get("ts_start", 0) >= cutoff)

    def active_count(self) -> int:
        n = len(self.children) + len(self.dry_active)
        if self.cfg.get("api_check", False) and not self.dry:
            try:
                r = subprocess.run(["opencode", "api", "get", "/api/session/active"],
                                   capture_output=True, text=True, timeout=15)
                n += len(json.loads(r.stdout).get("data", {}))
            except Exception:
                pass
        return n

    def lane_locked(self, lane: str) -> bool:
        p = self.cd / "locks" / f"{lane}.lock"
        if not p.exists():
            return False
        try:
            fd = os.open(p, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            return True
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True
        finally:
            os.close(fd)

    def hold_lane_lock(self, lane: str) -> int | None:
        p = self.cd / "locks" / f"{lane}.lock"
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        self.held_locks[lane] = fd
        return fd

    def release_lane_lock(self, lane: str) -> None:
        fd = self.held_locks.pop(lane, None)
        if fd is not None:
            with contextlib.suppress(Exception):
                fcntl.flock(fd, fcntl.LOCK_UN)
            with contextlib.suppress(Exception):
                os.close(fd)

    def _record_launch(self, kind: str, lane: str, cmd: list, cwd: str, log: str | None,
                       pid: int | None = None) -> None:
        append_jsonl(self.runs_path, {
            "ts_start": now(), "kind": kind, "lane": lane, "cmd": cmd, "cwd": cwd,
            "log": log, "dry_run": self.dry, "pid": pid,
        }, self.cd)

    def _record_exit(self, lane: str, exit_code: int, started: float) -> None:
        append_jsonl(self.runs_path, {
            "ts_end": now(), "lane": lane, "exit": exit_code,
            "duration_s": round(now() - started, 1), "dry_run": self.dry,
        }, self.cd)

    def _fail(self, st: dict, lane: str, reason: str) -> None:
        meta = st["lanes"].setdefault(lane, {})
        meta["failures"] = int(meta.get("failures", 0)) + 1
        f = meta["failures"]
        if "429" in reason or "rate" in reason.lower():
            base = int(self.cfg.get("failure_backoff_base_s", 30))
            cap = int(self.cfg.get("failure_backoff_max_s", 900))
            meta["backoff_until"] = now() + min(base * (2 ** f), cap)
            self.log(f"{lane}: rate/429 error -> backoff {int(meta['backoff_until'] - now())}s")
        if f >= int(self.cfg.get("max_consecutive_failures", 3)):
            if not meta.get("paused"):
                meta["paused"] = True
                self.attention(f"lane '{lane}' paused after {f} consecutive failures: {reason}")

    def _succeed(self, st: dict, lane: str) -> None:
        meta = st["lanes"].setdefault(lane, {})
        meta["failures"] = 0
        meta["backoff_until"] = None

    # ------------------------------------------------------------ wakes
    def _try_ping(self, sid: str, msg: str) -> str:
        """API prompt injection into an existing session -> 'ok' | '404' | 'error'.
        steer first (works while idle AND busy — busy processes it in order), then an
        explicit queue retry on non-404 failures."""
        for delivery in ("steer", "queue"):
            payload = json.dumps({"text": msg, "delivery": delivery})
            try:
                r = subprocess.run(
                    ["opencode", "api", "post", f"/api/session/{sid}/prompt",
                     "--data", payload],
                    capture_output=True, text=True, timeout=60)
                out = (r.stdout or "") + (r.stderr or "")
                if r.returncode == 0 and '"data"' in (r.stdout or ""):
                    return "ok"
            except Exception as e:
                out = str(e)
            if "404" in out or "NotFound" in out:
                return "404"
        return "error"

    def wake_lane(self, st: dict, lane: str, reason: str) -> bool:
        meta = st["lanes"].setdefault(lane, {})
        if meta.get("paused"):
            self.log(f"{lane}: paused — not waking")
            return False
        bu = meta.get("backoff_until")
        if bu and now() < bu:
            self.log(f"{lane}: backoff until {int(bu)} — queued")
            st.setdefault("run_queue", [])
            if lane not in st["run_queue"]:
                st["run_queue"].append(lane)
            return False
        if self.active_count() >= int(self.cfg.get("max_parallel_runs", 3)):
            st.setdefault("run_queue", [])
            if lane not in st["run_queue"]:
                st["run_queue"].append(lane)
            self.log(f"{lane}: at capacity ({self.active_count()}) — queued")
            return False
        if self.runs_last_hour() >= int(self.cfg.get("runs_per_hour", 12)):
            st.setdefault("run_queue", [])
            if lane not in st["run_queue"]:
                st["run_queue"].append(lane)
            self.log(f"{lane}: runs/hour cap — queued")
            return False

        sid = meta.get("session_id")
        if not sid and self.cfg.get("api_check", False):
            sid = coord.find_session(self.cd, lane, st)
            if sid:
                meta["session_id"] = sid

        # ---- dry-run: record the intended wake, treat as active for the cap
        if self.dry:
            kind = "ping" if sid else "headless"
            append_jsonl(self.dry_path, {
                "ts": now(), "lane": lane, "kind": kind, "session": sid,
                "reason": reason,
            }, self.cd)
            self._record_launch(f"dry-{kind}", lane, [], "", None)
            self.dry_active.add(lane)
            self.log(f"[dry-run] would {'ping ' + str(sid) if sid else 'headless-launch'} "
                     f"{lane} ({reason})")
            return True

        # ---- ping the lane's existing session (context preserved, zero idle cost)
        if sid:
            msg = self.cfg.get(
                "ping_msg",
                "coord wake: read your inbox and ~/.raphael-coord/prompts/lane_continue.md, "
                "then continue your work loop. Report via coord.").replace("{lane}", lane)
            res = self._try_ping(sid, msg)
            if res == "ok":
                meta["last_ping"] = now()
                self._succeed(st, lane)
                self._record_launch("ping", lane, ["opencode", "api", "post",
                                                   f"session/{sid}/prompt"], "", None)
                self.log(f"pinged {lane} ({sid}) — {reason}")
                return True
            if res == "404":
                meta["session_id"] = None   # stale id -> fall through to headless
                self.log(f"{lane}: session {sid} gone (404) — falling back")
            else:
                self._fail(st, lane, "ping failed")
                self._record_launch("ping-fail", lane, [], "", None)
                self.log(f"ping FAILED {lane} — counted as a failure")
                return False

        # ---- headless fallback: only if no session exists AND the worktree lock is free
        if self.lane_locked(lane):
            self.log(f"{lane}: lane lock held (interactive session) — no headless launch")
            return False
        wt = Path(self.cfg.get("wt_root", "/home/dami/raphael-wt")) / lane
        if not wt.is_dir():
            self.log(f"{lane}: no session and no worktree at {wt} — nothing to wake")
            return False
        if self.hold_lane_lock(lane) is None:
            self.log(f"{lane}: could not take lane lock — skipping")
            return False
        cmd = self.fmt("lane_headless_cmd", lane)
        logf = self.cd / "logs" / "runs" / f"lane-{lane}-{int(now())}.log"
        logf.parent.mkdir(parents=True, exist_ok=True)
        try:
            p = subprocess.Popen(cmd, cwd=str(wt), start_new_session=True,
                                 stdout=logf.open("wb"), stderr=subprocess.STDOUT)
        except Exception as e:
            self.release_lane_lock(lane)
            self._fail(st, lane, str(e))
            self.log(f"{lane}: headless spawn failed: {e}")
            return False
        self.children[p.pid] = {"lane": lane, "kind": "lane", "start": now(),
                                "log": str(logf), "cmd": cmd, "proc": p}
        self._save_children()
        self._record_launch("headless", lane, cmd, str(wt), str(logf), pid=p.pid)
        self.log(f"launched headless {lane} pid={p.pid} ({reason})")
        return True

    def wake_integrator(self, st: dict) -> bool:
        sid = st.get("lanes", {}).get("integrator", {}).get("session_id")
        pending = self.integrator_pending(st, self.cd)
        if self.dry:
            append_jsonl(self.dry_path, {
                "ts": now(), "lane": "integrator",
                "kind": "ping" if sid else "integrator",
                "reason": "unread events", "msg": "run integrator_event handler",
            }, self.cd)
            self._record_launch("dry-integrator", "integrator", [], "", None)
            self.log("[dry-run] would run the integrator event handler")
            return True

        # PRIMARY: ping the long-lived integrator session — it idles at zero cost,
        # keeps context, and wakes exactly once per debounced batch (delegation pattern).
        if sid:
            msg = self.cfg.get(
                "integrator_ping_msg",
                "coord wake: {pending} unread coord event(s). Handle them per "
                "~/.raphael-coord/prompts/integrator_event.md (read state.json + your "
                "inbox, process events, advance cursors, reply decisions), then go "
                "idle. Idempotent: nothing new = say so and end your turn."
            ).replace("{pending}", str(pending))
            res = self._try_ping(sid, msg)
            if res == "ok":
                self._record_launch("ping-integrator", "integrator",
                                    ["opencode", "api", "post",
                                     f"session/{sid}/prompt"], "", None)
                self.log(f"pinged integrator session ({sid}) — {pending} pending event(s)")
                return True
            if res == "404":
                st["lanes"].setdefault("integrator", {})["session_id"] = None
                self.log("integrator session gone (404) — falling back to a fresh run")
            else:
                self.log("integrator ping failed — falling back to a fresh run")

        # FALLBACK: fresh headless run (files are the memory — no context growth)
        cmd = self.fmt("integrator_cmd", "integrator")
        cwd = self.cfg.get("integrator_cwd", str(Path(__file__).resolve().parents[2]))
        logf = self.cd / "logs" / "runs" / f"integrator-{int(now())}.log"
        logf.parent.mkdir(parents=True, exist_ok=True)
        try:
            p = subprocess.Popen(cmd, cwd=cwd, start_new_session=True,
                                 stdout=logf.open("wb"), stderr=subprocess.STDOUT)
        except Exception as e:
            self.log(f"integrator spawn failed: {e}")
            return False
        self.children[p.pid] = {"lane": "integrator", "kind": "integrator", "start": now(),
                                "log": str(logf), "cmd": cmd, "proc": p}
        self._save_children()
        self._record_launch("integrator", "integrator", cmd, cwd, str(logf), pid=p.pid)
        self.log(f"launched integrator event handler pid={p.pid}")
        return True

    # ------------------------------------------------------------ ticks
    @staticmethod
    def refresh_from_events(st: dict, cd: Path) -> None:
        for lane in LANES:
            evs = read_jsonl(cd / "events" / f"{lane}.jsonl")
            if not evs:
                continue
            last = evs[-1]
            meta = st["lanes"].setdefault(lane, {})
            meta["last_event_type"] = last.get("type")
            if last.get("type") == "heartbeat":
                meta["heartbeat"] = last.get("ts")
                data = last.get("data") or {}
                if data.get("session_id"):
                    meta["session_id"] = data["session_id"]
                if data.get("branch_head"):
                    meta["branch_head"] = data["branch_head"]

    @staticmethod
    def integrator_pending(st: dict, cd: Path) -> int:
        return sum(max(0, line_count(cd / "events" / f"{lane}.jsonl")
                       - int(st["cursors"].get(lane, 0))) for lane in LANES)

    def check_integrator(self, st: dict) -> None:
        pending = self.integrator_pending(st, self.cd)
        if pending == 0:
            self.pending_since = None
            st["integrator_pending_since"] = None
            return
        if self.pending_since is None:
            self.pending_since = now()
            st["integrator_pending_since"] = self.pending_since
        if now() - self.pending_since < float(self.cfg.get("debounce_s", 75)):
            return
        if any(m.get("kind") == "integrator" for m in self.children.values()):
            return
        if st.get("integrator_wakes_disabled"):
            return
        if self.runs_last_hour() >= int(self.cfg.get("runs_per_hour", 12)):
            self.log("integrator wake: runs/hour cap reached — waiting")
            return
        sig = list(tuple(st["cursors"].get(l, 0) for l in LANES) + (pending,))
        # NOTE: compare as list — tuples round-trip through JSON as lists
        if st.get("last_wake_signature") == sig:
            if not self.dry:   # dry wakes never execute; only real runs count
                st["wake_misses"] = int(st.get("wake_misses", 0)) + 1
                if st["wake_misses"] >= 2:
                    st["integrator_wakes_disabled"] = True
                    self.attention("loop guard: integrator woke twice without advancing the "
                                   "event cursor — wakes disabled until a human resets")
            return
        st["last_wake_signature"] = sig
        st["wake_misses"] = 0
        self.wake_integrator(st)

    def check_wave(self, st: dict) -> None:
        wave = int(st["current_wave"])
        seen = int(st.get("conductor_seen_wave", wave))
        if wave == seen:
            return
        self.log(f"WAVE OPEN: {seen} -> {wave}")
        st["conductor_seen_wave"] = wave
        st.setdefault("wave_launches", {})[str(wave)] = []
        for lane in self.priority():
            meta = st["lanes"].setdefault(lane, {})
            if meta.get("paused"):
                continue
            meta["wave_role"] = "active" if wave >= self.min_wave(lane) else "standby"
            if meta["wave_role"] != "active":
                self.log(f"{lane}: standby (needs wave >= {self.min_wave(lane)})")
                continue
            # inbox wave_open is posted by the integrator handler (single owner);
            # the conductor's job here is only to WAKE eligible lanes
            if self.wake_lane(st, lane, f"wave {wave} open"):
                st["wave_launches"][str(wave)].append(lane)

    def drain_queue(self, st: dict) -> None:
        q = st.get("run_queue") or []
        if not q:
            return
        for lane in list(self.priority()):
            if lane not in q:
                continue
            if self.active_count() >= int(self.cfg.get("max_parallel_runs", 3)):
                break
            if self.wake_lane(st, lane, "queue drain"):
                q.remove(lane)

    def reap_children(self, st: dict) -> None:
        timeout = float(self.cfg.get("run_timeout_s", 2700))
        for pid, meta in list(self.children.items()):
            proc = meta.get("proc")
            exited, code = False, None
            if proc is not None:
                rc = proc.poll()                 # Popen-owned reap: no double-wait races
                if rc is not None:
                    exited, code = True, rc      # int: >=0 exit code, <0 signal
            else:
                try:
                    wp, status = os.waitpid(pid, os.WNOHANG)
                    if wp == pid:
                        exited, code = True, os.waitstatus_to_exitcode(status)
                except ChildProcessError:
                    # reaped elsewhere: code unknown — treat as FAILURE (never as
                    # success, or the failure caps could never trigger)
                    exited, code = True, 1
            if not exited:
                if now() - meta["start"] > timeout:
                    self.log(f"TIMEOUT {meta['kind']} {meta['lane']} pid={pid} "
                             f"after {int(timeout)}s — killing")
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(pid, signal.SIGTERM)
                    time.sleep(float(self.cfg.get("kill_grace_s", 2)))
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(pid, signal.SIGKILL)
                    self._record_exit(meta["lane"], -9, meta["start"])
                    self._fail(st, meta["lane"], "timeout")
                    st.setdefault("run_queue", [])
                    if meta["lane"] not in st["run_queue"]:
                        st["run_queue"].append(meta["lane"])
                    self.children.pop(pid, None)
                    self._save_children()
                    self.release_lane_lock(meta["lane"])
                continue
            self._record_exit(meta["lane"], code, meta["start"])
            logtail = ""
            if meta.get("log"):
                with contextlib.suppress(OSError):
                    logtail = Path(meta["log"]).read_text(errors="replace")[-2000:]
            if meta["kind"] == "integrator":
                if code == 0:
                    self.log(f"integrator handler exited 0 ({round(now() - meta['start'], 1)}s)")
                    st["wake_misses"] = 0
                else:
                    self.attention(f"integrator handler failed (exit {code}) — see {meta.get('log')}")
            elif meta["kind"] == "lane":
                if code == 0:
                    self._succeed(st, meta["lane"])
                    self.log(f"lane {meta['lane']} run finished ok "
                             f"({round(now() - meta['start'], 1)}s)")
                else:
                    reason = ("429" if ("429" in logtail or "rate limit" in logtail.lower())
                              else f"exit {code}")
                    self._fail(st, meta["lane"], reason)
                    st.setdefault("run_queue", [])
                    if meta["lane"] not in st["run_queue"]:
                        st["run_queue"].append(meta["lane"])
                    self.log(f"lane {meta['lane']} run FAILED: {reason}")
            self.release_lane_lock(meta["lane"])
            self.children.pop(pid, None)
            self._save_children()

    def check_sweep(self, st: dict) -> None:
        """Backstop against pipeline stalls: if NO events are pending but some lane is
        adopted, wave-active, unpaused and has an EMPTY inbox (nobody has ever spoken to
        it), wake the integrator for a board review. Lanes with any inbox content are
        driven by their own task_done events instead; standby lanes (start conditions)
        are excluded by wave_role. Runs at most once per sweep_s."""
        interval = float(self.cfg.get("sweep_s", 600))
        last = float(st.get("last_sweep", 0) or 0)
        if now() - last < interval:
            return
        st["last_sweep"] = now()
        if self.integrator_pending(st, self.cd) > 0:
            return                      # the normal debounced wake handles events
        if st.get("integrator_wakes_disabled"):
            return
        if any(m.get("kind") == "integrator" for m in self.children.values()):
            return
        if self.runs_last_hour() >= int(self.cfg.get("runs_per_hour", 12)):
            return
        stranded = [
            lane for lane in LANES
            if not st["lanes"].get(lane, {}).get("paused")
            and st["lanes"].get(lane, {}).get("wave_role") == "active"
            and st["lanes"].get(lane, {}).get("heartbeat")
            and line_count(self.cd / "inbox" / f"{lane}.jsonl") == 0
        ]
        if stranded:
            self.log(f"SWEEP: stranded lane(s) with empty inbox: {stranded}")
            # wake through the normal path (ping-primary, headless fallback)
            sig = ["sweep", int(now())]
            st["last_wake_signature"] = sig
            st["wake_misses"] = 0
            self.wake_integrator(st)

    def check_stall(self, st: dict) -> None:
        if not self.cfg.get("api_check", False) or self.dry:
            return
        limit = float(self.cfg.get("stall_heartbeat_s", 1200))
        try:
            r = subprocess.run(["opencode", "api", "get", "/api/session/active"],
                               capture_output=True, text=True, timeout=15)
            active = json.loads(r.stdout).get("data", {})
        except Exception:
            return
        for lane in LANES:
            meta = st["lanes"].get(lane, {})
            sid = meta.get("session_id")
            if not sid or sid not in active:
                continue
            hb = meta.get("heartbeat")
            if hb and now() - hb > limit and now() - self.stall_notified.get(lane, 0) > 3600:
                self.stall_notified[lane] = now()
                self.attention(f"lane '{lane}' session is running but its heartbeat is "
                               f"{int(now() - hb)}s stale — check that session")

    def tick_once(self) -> None:
        if (self.cd / "STOP").exists():
            self.log("STOP file present — shutting down cleanly")
            self.stop = True
            return
        # 1) read state (short lock, released)
        st = read_state(self.cd)
        # 2) compute + do all side effects WITHOUT holding the state lock
        self.refresh_from_events(st, self.cd)
        self.check_integrator(st)
        self.check_sweep(st)
        self.check_wave(st)
        self.reap_children(st)
        self.drain_queue(st)
        self.check_stall(st)
        # 3) write state back (short lock, released)
        write_state(self.cd, st)

    # ------------------------------------------------------------ main loop
    def cleanup_children(self) -> None:
        for pid, meta in list(self.children.items()):
            self.log(f"terminating managed child {meta['kind']} {meta['lane']} pid={pid}")
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGTERM)
            self.release_lane_lock(meta["lane"])
        self.children.clear()
        self._save_children()

    def run_loop(self) -> int:
        cd = self.cd
        (cd / "logs").mkdir(parents=True, exist_ok=True)
        lock = flock(cd / "locks" / "conductor.lock", blocking=False)
        try:
            lock.__enter__()
        except BlockingIOError:
            print("conductor: another instance is running — exiting")
            return 1
        (cd / "logs" / "conductor.pid").write_text(str(os.getpid()))
        (cd / "logs" / "conductor.meta.json").write_text(json.dumps(
            {"running": True, "pid": os.getpid(), "dry": self.dry, "tick": self.tick,
             "started": now()}))
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, lambda *_: setattr(self, "stop", True))
        self.log(f"conductor loop start (dry_run={self.dry}, tick={self.tick}s, "
                 f"max_parallel={self.cfg.get('max_parallel_runs', 3)}, "
                 f"api_check={self.cfg.get('api_check', False)})")
        try:
            while not self.stop:
                try:
                    self.tick_once()
                except Exception as e:
                    self.log(f"tick error: {e!r}")
                end = now() + self.tick
                while not self.stop and now() < end:
                    if (cd / "STOP").exists():
                        self.log("STOP file present — shutting down cleanly")
                        self.stop = True
                    time.sleep(min(0.5, max(0.05, end - now())))
        finally:
            self.cleanup_children()
            with contextlib.suppress(Exception):
                (cd / "logs" / "conductor.pid").unlink()
            lock.__exit__(None, None, None)
            self.log("conductor loop exit")
        return 0


def load_cfg(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def cmd_start(args) -> int:
    cd = coord_dir()
    if (cd / "STOP").exists():
        print("conductor: STOP file exists — the kill switch is armed. "
              "Remove ~/.raphael-coord/STOP first.")
        return 1
    running = coord.conductor_running(cd)
    if running:
        print(f"conductor: already running (pid {running})")
        return 0
    inner = [sys.executable, str(Path(__file__).resolve()), "loop", "--config", str(args.config)]
    if args.dry_run:
        inner.append("--dry-run")
    if args.tick:
        inner += ["--tick", str(args.tick)]
    cmd = " ".join(shlex.quote(x) for x in inner)
    r = subprocess.run(["tmux", "new-session", "-d", "-s", TMUX_SESSION, cmd],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"conductor: tmux failed: {r.stderr.strip()}")
        return 1
    print(f"conductor: started in tmux session '{TMUX_SESSION}' (dry_run={args.dry_run}); "
          f"watch with: tmux attach -t {TMUX_SESSION}  (detach: Ctrl-b d)")
    return 0


def cmd_stop(args) -> int:
    cd = coord_dir()
    (cd / "STOP").touch()
    # belt & braces: SIGTERM any managed children recorded by a previous/dead loop
    kids = cd / "logs" / "conductor.children.json"
    killed = 0
    if kids.exists():
        try:
            for pid in json.loads(kids.read_text()):
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(int(pid), signal.SIGTERM)
                    killed += 1
        except Exception:
            pass
    subprocess.run(["tmux", "kill-session", "-t", TMUX_SESSION], capture_output=True)
    print(f"conductor: STOP armed (kill switch), tmux session killed, "
          f"{killed} managed child(ren) sent SIGTERM")
    return 0


def cmd_status(args) -> int:
    cd = coord_dir()
    pid = coord.conductor_running(cd)
    print(f"conductor: {'RUNNING pid=' + str(pid) if pid else 'not running'}")
    if (cd / "STOP").exists():
        print("  STOP file: PRESENT (kill switch armed — start will refuse)")
    st = read_state(cd)
    pending = sum(max(0, line_count(cd / "events" / f"{l}.jsonl") - st["cursors"].get(l, 0))
                  for l in LANES)
    print(f"  wave={st['current_wave']} conductor_seen_wave={st.get('conductor_seen_wave')} "
          f"pending_events={pending}")
    paused = [l for l, m in st["lanes"].items() if m.get("paused")]
    print(f"  paused lanes: {', '.join(paused) if paused else 'none'}")
    if st.get("integrator_wakes_disabled"):
        print("  integrator wakes: DISABLED by loop guard (needs human reset)")
    runs = read_jsonl(cd / "logs" / "runs.jsonl")
    last_h = sum(1 for r in runs if r.get("ts_start", 0) >= now() - 3600)
    print(f"  launch records: {len(runs)} total, {last_h} in the last hour")
    log = cd / "logs" / "conductor.log"
    if log.exists():
        print("  last log lines:")
        for line in log.read_text(errors="replace").splitlines()[-8:]:
            print(f"    {line}")
    return 0


def cmd_pause(args) -> int:
    cd = coord_dir()

    def _p(st):
        st["lanes"].setdefault(args.lane, {})["paused"] = True
    mutate_state_local(cd, _p)
    print(f"conductor: {args.lane} paused (no wakes)")
    return 0


def cmd_resume(args) -> int:
    cd = coord_dir()

    def _r(st):
        m = st["lanes"].setdefault(args.lane, {})
        m["paused"] = False
        m["failures"] = 0
        m["backoff_until"] = None
        if args.lane == "integrator":
            st["integrator_wakes_disabled"] = False
            st["wake_misses"] = 0
    mutate_state_local(cd, _r)
    print(f"conductor: {args.lane} resumed")
    return 0


def mutate_state_local(cd, fn):
    """read-modify-write under ONE short state.lock section (no nesting)."""
    from coord import mutate_state
    return mutate_state(cd, fn)


def cmd_loop(args) -> int:
    cfg = load_cfg(Path(args.config))
    return Conductor(cfg, args.dry_run, args.tick).run_loop()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="conductor", description="Raphael coordination conductor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    default_cfg = str(coord_dir() / "conductor.yaml")

    s = sub.add_parser("start", help="start the conductor in tmux")
    s.add_argument("--config", default=default_cfg)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--tick", type=float)
    s.set_defaults(fn=cmd_start)

    s = sub.add_parser("stop", help="arm STOP kill switch + kill tmux + SIGTERM children")
    s.set_defaults(fn=cmd_stop)

    s = sub.add_parser("status", help="conductor status")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("pause", help="pause wakes for a lane")
    s.add_argument("lane", choices=LANES)
    s.set_defaults(fn=cmd_pause)

    s = sub.add_parser("resume", help="resume wakes for a lane")
    s.add_argument("lane", choices=LANES)
    s.set_defaults(fn=cmd_resume)

    s = sub.add_parser("loop", help="internal: run the watch loop in the foreground")
    s.add_argument("--config", default=default_cfg)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--tick", type=float)
    s.set_defaults(fn=cmd_loop)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
