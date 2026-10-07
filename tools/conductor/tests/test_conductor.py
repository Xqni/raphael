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
from pathlib import Path

HERE = Path(__file__).resolve().parent
CDIR = HERE.parent
sys.path.insert(0, str(CDIR))

import conductor as cond  # noqa: E402
import coord  # noqa: E402

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
    "repo_root": "/home/dami/raphael",
    "wt_root": "",           # per-test
    "integrator_cwd": "/home/dami/raphael",
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


class TestLoopGuard(CBase):
    def test_two_unadvanced_wakes_disable_integrator(self):
        coord.main(["post", "--lane", "infra", "--type", "error", "--msg", "boom"])
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


class TestPauseResume(CBase):
    def test_pause_blocks_wake_resume_re_enables(self):
        cond.main(["pause", "infra"])
        self.assertTrue(self.st()["lanes"]["infra"]["paused"])
        cond.main(["resume", "infra"])
        self.assertFalse(self.st()["lanes"]["infra"]["paused"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
