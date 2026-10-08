#!/usr/bin/env python3
"""Conductor unit tests — dry-run wakes, STOP kill switch, failure caps, 429 backoff,
loop guard, run timeout. No opencode invocations, no models, no network.

Run:  python3 tools/conductor/tests/test_conductor.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
CDIR = HERE.parent
sys.path.insert(0, str(CDIR))

import conductor as cond  # noqa: E402
from coord import line_count  # noqa: E402
import coord  # noqa: E402
REPO_ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[2])

BASE_CFG = {
    "tick_s": 0.2,
    "debounce_s": 0,
    "max_parallel_runs": 3,
    "runs_per_hour": 100,
    "run_timeout_s": 2700,
    "max_consecutive_failures": 3,
    "stall_heartbeat_s": 1200,
    "failure_backoff_base_s": 0,
    "failure_backoff_max_s": 0,
    "model": "test-model",
    "dry_run": False,
    "api_check": False,
    "priority": ["infra", "router", "brain-core", "orb", "voice", "pc-control",
                 "computer-use", "qa-security", "tools-memory", "evolution-persona"],
    "start_conditions": {"tools-memory": {"min_wave": 3},
                         "evolution-persona": {"min_wave": 4}},
    "repo_root": REPO_ROOT,
    "wt_root": "",           # per-test
    "integrator_cwd": REPO_ROOT,
    "integrator_cmd": ["/bin/true"],
    "integrator_prompt": "prompts/integrator_event.md",
    "lane_headless_cmd": ["/bin/false"],
    "lane_prompt": "prompts/lane_continue.md",
    "kill_grace_s": 0.2,
    "ping_msg": "wake {lane}",
}


class CBase(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="cond-test-"))
        os.environ["RAPHAEL_COORD_DIR"] = str(self.d)
        os.environ["COORD_NO_TOAST"] = "1"
        self.wt = self.d / "wt"
        for ln in coord.LANES:
            (self.wt / ln).mkdir(parents=True, exist_ok=True)
        coord.main(["init"])
        self.cfg = dict(BASE_CFG, wt_root=str(self.wt))

    def tearDown(self):
        for pidf in (self.d / "locks").glob("*.pid"):
            try:
                os.kill(int(pidf.read_text()), 9)
            except Exception:
                pass
        shutil.rmtree(self.d, ignore_errors=True)

    def mk(self, dry: bool) -> cond.Conductor:
        return cond.Conductor(json.loads(json.dumps(self.cfg)), dry, 0.05)

    def st(self) -> dict:
        return coord.read_state(self.d)

    def set_state(self, **over):
        st = coord.read_state(self.d)
        st.update(over)
        coord.write_state(self.d, st)

    def attn(self) -> str:
        return (self.d / "ATTENTION.md").read_text()


class TestDryWake(CBase):
    def test_wave_open_caps_and_priority(self):
        self.set_state(conductor_seen_wave=1, current_wave=2)
        c = self.mk(dry=True)
        c.tick_once()
        launches = [e["lane"] for e in coord.read_jsonl(c.dry_path)]
        self.assertEqual(launches, ["infra", "router", "brain-core"])   # cap 3 + priority
        st = self.st()
        self.assertEqual(st["run_queue"],
                         ["orb", "voice", "pc-control", "computer-use", "qa-security"])
        self.assertEqual(st["lanes"]["tools-memory"]["wave_role"], "standby")
        self.assertEqual(st["lanes"]["evolution-persona"]["wave_role"], "standby")
        self.assertEqual(st["conductor_seen_wave"], 2)
        # wave_open inbox messages are the INTEGRATOR HANDLER's job (single owner) —
        # the conductor must not double-post them
        inbox = coord.read_jsonl(self.d / "inbox" / "voice.jsonl")
        self.assertFalse(any(m["type"] == "wave_open" for m in inbox))

    def test_dry_integrator_wake_and_no_loop_guard_in_dry(self):
        coord.main(["post", "--lane", "qa-security", "--type", "task_done", "--msg", "x"])
        c = self.mk(dry=True)
        for _ in range(5):
            c.tick_once()
            time.sleep(0.05)
        launches = [e["lane"] for e in coord.read_jsonl(c.dry_path)]
        self.assertEqual(launches, ["integrator"])          # exactly one wake (debounce 0)
        st = self.st()
        self.assertFalse(st.get("integrator_wakes_disabled"))  # dry never counts misses


class TestStop(CBase):
    def test_stop_file_exits_loop_cleanly(self):
        (self.d / "STOP").touch()
        r = subprocess.run(
            [sys.executable, str(CDIR / "conductor.py"), "loop",
             "--config", "/nonexistent", "--dry-run", "--tick", "0.2"],
            capture_output=True, text=True, env=dict(os.environ), timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("STOP file present", r.stdout)
        # and conductor start refuses while STOP is armed
        r2 = subprocess.run([sys.executable, str(CDIR / "conductor.py"), "start"],
                            capture_output=True, text=True, env=dict(os.environ), timeout=30)
        self.assertEqual(r2.returncode, 1)
        self.assertIn("kill switch", r2.stdout)


class TestFailureCaps(CBase):
    def test_three_failures_pause_and_attention(self):
        # only router eligible: everything else paused; headless cmd = /bin/false
        st = self.st()
        for ln in coord.LANES:
            if ln != "router":
                st["lanes"][ln]["paused"] = True
        st["conductor_seen_wave"] = 1          # wave-open on first tick
        coord.write_state(self.d, st)
        c = self.mk(dry=False)
        paused_at = None
        for i in range(60):
            c.tick_once()
            time.sleep(0.1)
            if self.st()["lanes"]["router"].get("paused"):
                paused_at = i
                break
        self.assertIsNotNone(
            paused_at,
            f"router never paused: {self.st()['lanes']['router']}\n"
            f"--- conductor.log ---\n"
            f"{(self.d / 'logs' / 'conductor.log').read_text() if (self.d / 'logs' / 'conductor.log').exists() else '(none)'}\n"
            f"--- runs ---\n{coord.read_jsonl(self.d / 'logs' / 'runs.jsonl')}")
        st2 = self.st()
        self.assertGreaterEqual(st2["lanes"]["router"]["failures"], 3)
        self.assertIn("paused after 3 consecutive failures", self.attn())
        # after the pause: no further launches
        n = len(coord.read_jsonl(self.d / "logs" / "runs.jsonl"))
        for _ in range(3):
            c.tick_once()
            time.sleep(0.1)
        n2 = len(coord.read_jsonl(self.d / "logs" / "runs.jsonl"))
        self.assertEqual(n, n2, "launched something after the pause")

    def test_429_sets_backoff_and_blocks_wake(self):
        self.cfg["failure_backoff_base_s"] = 30
        self.cfg["failure_backoff_max_s"] = 300
        c = self.mk(dry=True)
        st = self.st()
        c._fail(st, "voice", "429 rate limit exceeded")
        self.assertGreater(st["lanes"]["voice"]["backoff_until"], time.time())
        self.assertEqual(st["lanes"]["voice"]["failures"], 1)
        ok = c.wake_lane(st, "voice", "test")
        self.assertFalse(ok)
        self.assertIn("voice", st.get("run_queue", []))


class TestDispatchEfficiency(CBase):
    def test_existing_session_ping_bypasses_headless_caps(self):
        """A reusable session wake is not a headless process spawn."""
        st = self.st()
        st["lanes"]["voice"]["session_id"] = "ses_existing"
        coord.write_state(self.d, st)
        c = self.mk(dry=False)
        c.active_count = lambda: 99
        c.runs_last_hour = lambda: 99
        pings = []
        c._try_ping = lambda sid, msg: pings.append(sid) or "ok"

        self.assertTrue(c.wake_lane(self.st(), "voice", "unit-test"))
        self.assertEqual(pings, ["ses_existing"])
        runs = coord.read_jsonl(c.runs_path)
        self.assertEqual(runs[-1]["kind"], "ping")

    def test_ping_records_do_not_consume_headless_hourly_budget(self):
        c = self.mk(dry=False)
        for i in range(20):
            c._record_launch("ping", "voice", [], "", None)
        self.assertEqual(c.runs_last_hour(), 0)
        c._record_launch("headless", "voice", ["opencode"], "/tmp/wt", None)
        self.assertEqual(c.runs_last_hour(), 1)

    def test_duplicate_session_ping_is_coalesced(self):
        st = self.st()
        st["lanes"]["voice"]["session_id"] = "ses_existing"
        coord.write_state(self.d, st)
        c = self.mk(dry=False)
        c.cfg["session_ping_cooldown_s"] = 90
        c._try_ping = lambda sid, msg: "ok"
        self.assertTrue(c.wake_lane(st, "voice", "first"))
        pings_before = len([r for r in coord.read_jsonl(c.runs_path) if r["kind"] == "ping"])
        self.assertFalse(c.wake_lane(st, "voice", "duplicate"))
        pings_after = len([r for r in coord.read_jsonl(c.runs_path) if r["kind"] == "ping"])
        self.assertEqual(pings_before, pings_after)
        self.assertIn("voice", st.get("run_queue", []))

    def test_stale_session_404_falls_back_to_headless_once(self):
        st = self.st()
        st["lanes"]["voice"]["session_id"] = "ses_deleted"
        coord.write_state(self.d, st)
        c = self.mk(dry=False)
        c.cfg["lane_headless_cmd"] = [sys.executable, "-c", "pass"]
        c._try_ping = lambda sid, msg: "404"
        st = self.st()
        self.assertTrue(c.wake_lane(st, "voice", "stale-session"))
        starts = [r for r in coord.read_jsonl(c.runs_path) if r["kind"] == "headless"]
        self.assertEqual(len(starts), 1)
        self.assertIsNone(st["lanes"]["voice"].get("session_id"))
        c.cleanup_children()

    def test_zero_exit_empty_prompt_response_is_not_retried(self):
        c = self.mk(dry=False)
        ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with mock.patch("conductor.subprocess.run", return_value=ok) as run:
            self.assertEqual(c._try_ping("ses_existing", "one wake"), "ok")
        self.assertEqual(run.call_count, 1, "empty 204 success must not enqueue a duplicate turn")


class TestLoopGuard(CBase):
    def test_two_unadvanced_wakes_disable_integrator(self):
        coord.main(["post", "--lane", "infra", "--type", "error", "--msg", "boom"])
        self.cfg["wake_grace_s"] = 0.15   # patient guard, sped up for the test
        c = self.mk(dry=False)      # integrator_cmd = /bin/true (runs, cursor never advances)
        disabled = False
        for _ in range(12):
            c.tick_once()
            time.sleep(0.1)
            st = self.st()
            if st.get("integrator_wakes_disabled"):
                disabled = True
                break
        self.assertTrue(disabled, "loop guard never fired")
        self.assertIn("loop guard", self.attn())
        # further ticks do not wake again
        launches = [r for r in coord.read_jsonl(self.d / "logs" / "runs.jsonl")
                    if r.get("kind") == "integrator"]
        n = len(launches)
        for _ in range(3):
            c.tick_once()
        launches2 = [r for r in coord.read_jsonl(self.d / "logs" / "runs.jsonl")
                     if r.get("kind") == "integrator"]
        self.assertEqual(len(launches2), n)


class TestPatientGuard(CBase):
    def test_no_miss_within_grace_window(self):
        coord.main(["post", "--lane", "infra", "--type", "error", "--msg", "boom"])
        self.cfg["wake_grace_s"] = 600   # long grace
        c = self.mk(dry=False)
        for _ in range(6):
            c.tick_once()
            time.sleep(0.05)
        st = self.st()
        self.assertEqual(st.get("wake_misses", 0), 0,
                         "guard counted a miss inside the grace window")
        self.assertFalse(st.get("integrator_wakes_disabled"))


class TestTimeout(CBase):
    def test_run_timeout_kills_and_fails(self):
        self.cfg["lane_headless_cmd"] = ["sleep", "30"]
        self.cfg["run_timeout_s"] = 0.5
        st = self.st()
        for ln in coord.LANES:
            if ln != "pc-control":
                st["lanes"][ln]["paused"] = True
        st["conductor_seen_wave"] = 1
        coord.write_state(self.d, st)
        c = self.mk(dry=False)
        paused = False
        for _ in range(60):
            c.tick_once()
            time.sleep(0.15)
            st2 = self.st()
            if st2["lanes"]["pc-control"].get("paused"):
                paused = True
                break
        self.assertTrue(paused, f"timeout failures never escalated: "
                                f"{self.st()['lanes']['pc-control']}")
        self.assertEqual(c.children, {}, "child not reaped after pause")
        log = (self.d / "logs" / "conductor.log").read_text()
        self.assertIn("TIMEOUT", log)
        self.assertIn("timeout", self.attn())


class TestSweep(CBase):
    """Backstop: stranded lane (adopted + wave-active + EMPTY inbox + no pending events)
    wakes the integrator; settled or standby lanes never do."""

    def _strand(self, lane="voice", inbox_empty=True, role="active"):
        st = self.st()
        st["lanes"][lane]["wave_role"] = role
        st["lanes"][lane]["heartbeat"] = time.time()
        st["conductor_seen_wave"] = st["current_wave"]   # no wave-open noise
        coord.write_state(self.d, st)
        if not inbox_empty:
            coord.main(["reply", "--lane", lane, "--type", "decision",
                        "--msg", "NEXT TASK: something"])

    def test_stranded_lane_triggers_sweep_wake(self):
        self.cfg["sweep_s"] = 0.3
        self._strand(inbox_empty=True, role="active")
        c = self.mk(dry=True)
        time.sleep(0.4)          # pass the sweep interval
        c.tick_once()
        wakes = [e for e in coord.read_jsonl(c.dry_path) if e["lane"] == "integrator"]
        self.assertEqual(len(wakes), 1, wakes)
        self.assertIn("SWEEP", (self.d / "logs" / "conductor.log").read_text())

    def test_no_sweep_when_inbox_settled(self):
        self.cfg["sweep_s"] = 0.3
        self._strand(inbox_empty=False, role="active")
        c = self.mk(dry=True)
        time.sleep(0.4)
        c.tick_once()
        wakes = [e for e in coord.read_jsonl(c.dry_path) if e["lane"] == "integrator"]
        self.assertEqual(wakes, [])

    def test_no_sweep_for_standby_lane(self):
        self.cfg["sweep_s"] = 0.3
        self._strand(inbox_empty=True, role="standby")
        c = self.mk(dry=True)
        time.sleep(0.4)
        c.tick_once()
        wakes = [e for e in coord.read_jsonl(c.dry_path) if e["lane"] == "integrator"]
        self.assertEqual(wakes, [])

    def test_sweep_interval_respected(self):
        self.cfg["sweep_s"] = 600      # long interval
        self._strand(inbox_empty=True, role="active")
        c = self.mk(dry=True)
        c.tick_once()                  # fires once (last_sweep starts at 0)
        c.tick_once()                  # inside the interval -> must NOT fire again
        wakes = [e for e in coord.read_jsonl(c.dry_path) if e["lane"] == "integrator"]
        self.assertEqual(len(wakes), 1, f"sweep fired twice inside one interval: {wakes}")


class TestCursorDurability(CBase):
    """Regression: a conductor tick must never clobber integrator-written state
    (2026-10-06: a stale full-overwrite reverted 8 cursor advances mid-turn)."""

    def test_cursor_advance_survives_conductor_tick(self):
        coord.main(["post", "--lane", "voice", "--type", "task_done", "--msg", "x"])
        coord.main(["cursor", "--lane", "voice", "--set", "1"])   # review-start advance
        c = self.mk(dry=True)
        c.tick_once()                       # refresh + conductor merge-write
        self.assertEqual(coord.read_cursors(self.d).get("voice"), 1,
                         "conductor tick reverted a cursor advance")
        ev = line_count(self.d / "events" / "voice.jsonl")
        self.assertEqual(ev - coord.read_cursors(self.d)["voice"], 0)

    def test_wave_bump_survives_conductor_tick(self):
        coord.main(["wave-bump", "--wave", "7"])
        c = self.mk(dry=True)
        c.tick_once()
        self.assertEqual(coord.read_state(self.d)["current_wave"], 7,
                         "conductor tick reverted current_wave")


class TestServerWatchdog(CBase):
    """User mandate 2026-10-06: NEVER multiple servers at once."""

    def _run(self, pids, live=False, enabled=True):
        self.cfg["server_watchdog"] = enabled
        c = self.mk(dry=True)
        killed = []
        c._pgrep = lambda pat: list(pids)
        c._kill = lambda pid: killed.append(pid)
        st = self.st()
        st["live_e2e"] = live
        c.check_server_sanity(st)
        return killed

    def test_multiple_servers_all_but_oldest_killed(self):
        killed = self._run([300, 111, 222], live=True)
        self.assertEqual(sorted(killed), [222, 300])   # oldest (111) kept

    def test_stray_killed_when_stack_off(self):
        self.assertEqual(self._run([555], live=False), [555])

    def test_single_server_exempt_during_live_e2e(self):
        self.assertEqual(self._run([555], live=True), [])

    def test_watchdog_can_be_disabled(self):
        self.assertEqual(self._run([1, 2], live=False, enabled=False), [])


class TestPauseResume(CBase):
    def test_pause_blocks_wake_resume_re_enables(self):
        cond.main(["pause", "infra"])
        self.assertTrue(self.st()["lanes"]["infra"]["paused"])
        cond.main(["resume", "infra"])
        self.assertFalse(self.st()["lanes"]["infra"]["paused"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
