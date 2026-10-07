#!/usr/bin/env python3
"""End-to-end coordination simulation (docs section 7) — fake lanes, no models, no network.

Scenario:
  1. two lanes post wave_done (+ heartbeat with session ids)
  2. the integrator handler runs (dry-run: merges mocked)
  3. the wave bumps 2 -> 3, wave_open lands in every lane inbox, cursors advance,
     rerun is a no-op (idempotent)
  4. the conductor (dry-run launcher) wakes the now-idle lanes: cap 3 + priority order,
     rest queued, `coord mode` = exit
  5. the kill switch (STOP) stops the conductor cleanly: exit 0, no further launches,
     `coord mode` = wait
  6. failure caps: a fresh non-dry conductor runs /bin/false for a lane 3x -> lane paused
     + ATTENTION entry

Run:  python3 tools/conductor/tests/test_e2e.py
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
COORD = CDIR / "coord.py"
HANDLER = CDIR / "handler_dryrun.py"
CONDUCTOR = CDIR / "conductor.py"
REPO = CDIR.parents[1]          # /home/dami/raphael


def wait_until(fn, timeout=20.0, interval=0.2, what="condition"):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {what}")


class TestCoordE2E(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="coord-e2e-"))
        self.wt = self.d / "wt"
        for ln in ("router", "brain-core", "pc-control", "voice", "computer-use",
                   "orb", "infra", "qa-security", "tools-memory", "evolution-persona"):
            (self.wt / ln).mkdir(parents=True, exist_ok=True)
        self.env = dict(os.environ,
                        RAPHAEL_COORD_DIR=str(self.d), COORD_NO_TOAST="1")
        self.procs: list[subprocess.Popen] = []

    def tearDown(self):
        # STOP file only (never `conductor stop` here: it would kill a REAL tmux session)
        try:
            (self.d / "STOP").touch()
        except OSError:
            pass
        for p in self.procs:
            if p.poll() is None:
                try:
                    p.communicate(timeout=8)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.communicate(timeout=5)
        shutil.rmtree(self.d, ignore_errors=True)

    # ------------------------------------------------------------ helpers
    def coord(self, *args, expect=0):
        r = subprocess.run([sys.executable, str(COORD), *args],
                           capture_output=True, text=True, env=self.env, timeout=60)
        if expect is not None and r.returncode != expect:
            raise AssertionError(f"coord {' '.join(args)} rc={r.returncode}\n"
                                 f"{r.stdout}\n{r.stderr}")
        return r

    def state(self) -> dict:
        return json.loads((self.d / "state.json").read_text())

    def set_state(self, **over):
        st = self.state()
        st.update(over)
        (self.d / "state.json").write_text(json.dumps(st, indent=1))

    def write_cfg(self, name: str, **over) -> str:
        cfg = {
            "tick_s": 0.2, "debounce_s": 0, "max_parallel_runs": 3,
            "runs_per_hour": 100, "run_timeout_s": 2700,
            "max_consecutive_failures": 3, "stall_heartbeat_s": 1200,
            "failure_backoff_base_s": 0, "failure_backoff_max_s": 0,
            "kill_grace_s": 0.2, "model": "test-model", "dry_run": False,
            "api_check": False,
            "priority": ["infra", "router", "brain-core", "orb", "voice", "pc-control",
                         "computer-use", "qa-security", "tools-memory",
                         "evolution-persona"],
            "start_conditions": {"tools-memory": {"min_wave": 3},
                                 "evolution-persona": {"min_wave": 4}},
            "repo_root": str(REPO), "wt_root": str(self.wt),
            "integrator_cwd": str(REPO),
            "integrator_cmd": ["/bin/true"],
            "integrator_prompt": "prompts/integrator_event.md",
            "lane_headless_cmd": ["/bin/false"],
            "lane_prompt": "prompts/lane_continue.md",
            "ping_msg": "wake {lane}",
        }
        cfg.update(over)
        p = self.d / name
        p.write_text(json.dumps(cfg))
        return str(p)

    def start_conductor(self, cfg: str, dry: bool) -> subprocess.Popen:
        cmd = [sys.executable, str(CONDUCTOR), "loop", "--config", cfg, "--tick", "0.2"]
        if dry:
            cmd.append("--dry-run")
        proc = subprocess.Popen(cmd, env=self.env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        self.procs.append(proc)
        return proc

    def stop_conductor(self, proc: subprocess.Popen, expect_rc=0) -> str:
        (self.d / "STOP").touch()
        out, _ = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, expect_rc, out[-2000:])
        return out

    # ------------------------------------------------------------ the scenario
    def test_full_scenario(self):
        # -- 0. init; wave 2; only router + voice active (others paused)
        self.coord("init")
        st = self.state()
        for ln in st["lanes"]:
            if ln not in ("router", "voice"):
                st["lanes"][ln]["paused"] = True
        st["current_wave"] = 2
        st["conductor_seen_wave"] = 2
        (self.d / "state.json").write_text(json.dumps(st, indent=1))

        # -- 1. two lanes report wave_done (+ heartbeats carrying session ids)
        self.coord("post", "--lane", "router", "--type", "heartbeat", "--msg", "task start",
                   "--data", '{"session_id":"ses_fake_router","branch_head":"aaaa111"}')
        self.coord("post", "--lane", "voice", "--type", "heartbeat", "--msg", "task start",
                   "--data", '{"session_id":"ses_fake_voice","branch_head":"bbbb222"}')
        self.coord("post", "--lane", "router", "--type", "wave_done",
                   "--msg", "router: groq+zen chain done, 10/10 router tests")
        self.coord("post", "--lane", "voice", "--type", "wave_done",
                   "--msg", "voice: STT seam done, 20/20 voice tests")

        # -- 2. the integrator handler runs (dry-run mocks the merges)
        h = subprocess.run(
            [sys.executable, str(HANDLER), "--mock-gate",
             "--wt-root", str(self.wt), "--repo-root", str(REPO)],
            capture_output=True, text=True, env=self.env, timeout=120)
        self.assertEqual(h.returncode, 0, h.stdout + h.stderr)
        self.assertIn("WAVE 2 -> 3 (mock gate)", h.stdout)

        # merged decisions landed in both inboxes
        for ln in ("router", "voice"):
            inbox = (self.d / "inbox" / f"{ln}.jsonl").read_text()
            self.assertIn("decision: merged agent/", inbox)
        # wave_open went to EVERY lane inbox (including never-active ones)
        for ln in st["lanes"]:
            inbox = (self.d / "inbox" / f"{ln}.jsonl").read_text()
            self.assertIn('"wave_open"', inbox)
        # cursors advanced -> wave bumped 2 -> 3
        self.assertEqual(self.state()["current_wave"], 3)
        curs = json.loads((self.d / "cursors.json").read_text())
        for ln in ("router", "voice"):
            self.assertEqual(curs[ln],
                             len((self.d / "events" / f"{ln}.jsonl").read_text().splitlines()))

        # idempotent rerun: no new events
        h2 = subprocess.run(
            [sys.executable, str(HANDLER), "--mock-gate",
             "--wt-root", str(self.wt), "--repo-root", str(REPO)],
            capture_output=True, text=True, env=self.env, timeout=120)
        self.assertEqual(h2.returncode, 0, h2.stdout + h2.stderr)
        self.assertIn("no new events", h2.stdout)

        # -- 3. unpaused lanes become idle-eligible for wave 3
        st = self.state()
        for ln in ("infra", "brain-core", "orb", "computer-use"):
            st["lanes"][ln]["paused"] = False
        (self.d / "state.json").write_text(json.dumps(st, indent=1))

        # -- 4. dry-run conductor wakes idle lanes (cap 3 + priority; rest queued)
        cfg = self.write_cfg("conductor.dry.json")
        proc = self.start_conductor(cfg, dry=True)
        try:
            wait_until(lambda: self.state().get("conductor_seen_wave") == 3,
                       what="conductor to observe wave 3")
            wait_until(lambda: len(self.read_dry()) >= 3,
                       what="3 dry wakes")
            time.sleep(0.6)   # let any extra ticks settle before asserting the cap
            dry = self.read_dry()
            self.assertEqual([e["lane"] for e in dry],
                             ["infra", "router", "brain-core"])   # priority + cap 3
            kinds = {e["lane"]: e["kind"] for e in dry}
            self.assertEqual(kinds["router"], "ping")        # session id from heartbeat
            self.assertEqual(kinds["infra"], "headless")     # no session -> fallback
            st = self.state()
            self.assertEqual(st["run_queue"], ["orb", "voice", "computer-use"])
            self.assertEqual(st["lanes"]["evolution-persona"]["wave_role"], "standby")
            self.assertEqual(st["lanes"]["tools-memory"]["wave_role"], "standby")
            # mode flips to exit while the conductor runs
            self.assertEqual(self.coord("mode", "--lane", "router").stdout.strip(), "exit")

            # -- 5. kill switch stops everything
            out = self.stop_conductor(proc)
            self.assertIn("STOP file present", out)
            n_launch = len(self.read_dry())
            time.sleep(1.0)
            self.assertEqual(len(self.read_dry()), n_launch,
                             "launched something after STOP")
            self.assertEqual(self.coord("mode", "--lane", "router").stdout.strip(), "wait")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate(timeout=10)

        # -- 6. failure caps (non-dry conductor, /bin/false lane runs)
        (self.d / "STOP").unlink()
        self.coord("wave-bump", "--wave", "4")
        st = self.state()
        for ln in st["lanes"]:
            st["lanes"][ln]["paused"] = ln != "qa-security"
        (self.d / "state.json").write_text(json.dumps(st, indent=1))

        cfg2 = self.write_cfg("conductor.fail.json")
        proc2 = self.start_conductor(cfg2, dry=False)
        try:
            wait_until(lambda: "paused after 3 consecutive failures" in
                       (self.d / "ATTENTION.md").read_text(),
                       timeout=30, what="failure cap attention")
            st = self.state()
            self.assertTrue(st["lanes"]["qa-security"]["paused"])
            self.assertGreaterEqual(st["lanes"]["qa-security"]["failures"], 3)
            out = self.stop_conductor(proc2)
            self.assertIn("STOP file present", out)
        finally:
            if proc2.poll() is None:
                proc2.kill()
                proc2.communicate(timeout=10)

        # summary for the report
        print("\n--- E2E artifacts ---")
        print(f"wave: {self.state()['current_wave']}  "
              f"pending: {sum(self.state()['cursors'].values()) and 'advanced'}")
        print(f"dry wakes: {[e['lane'] + ':' + e['kind'] for e in self.read_dry()]}")
        print(f"attention entries: "
              f"{self.d.joinpath('ATTENTION.md').read_text().count(chr(10) + '- [')}")

    def read_dry(self) -> list:
        p = self.d / "logs" / "launches.dryrun.jsonl"
        if not p.exists():
            return []
        out = []
        for line in p.read_text().splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out


if __name__ == "__main__":
    unittest.main(verbosity=2)
