#!/usr/bin/env python3
"""Unit tests for the coord bus CLI — stdlib unittest, no network, no models.

Run:  python3 tools/conductor/tests/test_coord.py
Every test gets a fresh RAPHAEL_COORD_DIR sandbox; COORD_NO_TOAST=1 (no Windows toasts).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONDUCTOR_DIR = HERE.parent
COORD = CONDUCTOR_DIR / "coord.py"
sys.path.insert(0, str(CONDUCTOR_DIR))
import coord as coord_module  # noqa: E402


def fresh_env() -> tuple[dict, Path]:
    d = Path(tempfile.mkdtemp(prefix="coord-test-"))
    env = dict(os.environ, RAPHAEL_COORD_DIR=str(d), COORD_NO_TOAST="1")
    return env, d


def run(env, *args, expect=0) -> subprocess.CompletedProcess:
    r = subprocess.run([sys.executable, str(COORD), *args],
                       capture_output=True, text=True, env=env, timeout=60)
    if expect is not None and r.returncode != expect:
        raise AssertionError(f"coord {' '.join(args)} -> rc={r.returncode}\n"
                             f"stdout: {r.stdout}\nstderr: {r.stderr}")
    return r


class CoordBase(unittest.TestCase):
    def setUp(self):
        self.env, self.d = fresh_env()
        run(self.env, "init")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    # ------------------------------------------------------------ layout
    def test_init_layout(self):
        for sub in ("bin/coord", "events", "inbox", "locks", "logs", "prompts",
                    "state.json", "ATTENTION.md"):
            self.assertTrue((self.d / sub).exists(), sub)
        self.assertTrue((self.d / "bin" / "coord").is_symlink())
        self.assertTrue(os.access(self.d / "bin" / "coord", os.X_OK))
        st = json.loads((self.d / "state.json").read_text())
        self.assertEqual(st["current_wave"], 2)
        self.assertIn("tools-memory", st["start_conditions"])

    # ------------------------------------------------------------ post / inbox
    def test_post_envelope_shape(self):
        run(self.env, "post", "--lane", "router", "--type", "task_done",
            "--msg", "built groq client", "--ref", "brain/router/groq.py",
            "--data", '{"tests": 3}')
        line = (self.d / "events" / "router.jsonl").read_text().strip()
        ev = json.loads(line)
        for k in ("ts", "lane", "type", "wave", "ref", "msg", "data"):
            self.assertIn(k, ev)
        self.assertEqual(ev["type"], "task_done")
        self.assertEqual(ev["wave"], 2)
        self.assertEqual(ev["data"], {"tests": 3})

    def test_post_rejects_bad_type_and_lane(self):
        run(self.env, "post", "--lane", "router", "--type", "nonsense", "--msg", "x", expect=None)
        r2 = subprocess.run([sys.executable, str(COORD), "post", "--lane", "nope",
                             "--type", "task_done", "--msg", "x"],
                            capture_output=True, text=True, env=self.env)
        self.assertNotEqual(r2.returncode, 0)
        self.assertFalse((self.d / "events" / "router.jsonl").read_text().strip())

    def test_inbox_unread_mark_read(self):
        run(self.env, "reply", "--lane", "voice", "--type", "decision", "--msg", "merged abc")
        run(self.env, "reply", "--lane", "voice", "--type", "nudge", "--msg", "second")
        out = run(self.env, "inbox", "--lane", "voice", "--unread").stdout
        self.assertEqual(out.count("\n"), 2)
        run(self.env, "inbox", "--lane", "voice", "--unread", "--mark-read")
        out2 = run(self.env, "inbox", "--lane", "voice", "--unread").stdout
        self.assertEqual(out2.strip(), "")
        out3 = run(self.env, "inbox", "--lane", "voice").stdout
        self.assertEqual(out3.count("\n"), 2)   # full inbox still visible

    def test_reply_rejects_event_types(self):
        r = subprocess.run([sys.executable, str(COORD), "reply", "--lane", "voice",
                            "--type", "wave_done", "--msg", "x"],
                           capture_output=True, text=True, env=self.env)
        self.assertNotEqual(r.returncode, 0)

    # ------------------------------------------------------------ wave / status / mode
    def test_wave_and_bump(self):
        self.assertEqual(run(self.env, "wave").stdout.strip(), "2")
        run(self.env, "wave-bump", "--wave", "3")
        self.assertEqual(run(self.env, "wave").stdout.strip(), "3")

    def test_status_json_pending(self):
        run(self.env, "post", "--lane", "infra", "--type", "error", "--msg", "boom")
        out = json.loads(run(self.env, "status", "--json").stdout)
        self.assertEqual(out["wave"], 2)
        self.assertEqual(out["lanes"]["infra"]["pending_events"], 1)
        self.assertFalse(out["conductor"]["running"])
        run(self.env, "cursor", "--lane", "infra")
        out2 = json.loads(run(self.env, "status", "--json").stdout)
        self.assertEqual(out2["lanes"]["infra"]["pending_events"], 0)

    def test_heartbeat_registers_session_id(self):
        run(self.env, "post", "--lane", "orb", "--type", "heartbeat", "--msg", "hi",
            "--data", '{"session_id":"ses_abc123","branch_head":"b2e80f6"}')
        st = json.loads((self.d / "state.json").read_text())
        self.assertEqual(st["lanes"]["orb"]["session_id"], "ses_abc123")
        out = json.loads(run(self.env, "status", "--json").stdout)
        self.assertEqual(out["lanes"]["orb"]["session_id"], "ses_abc123")

    def test_find_session_reads_opencode_v2_top_level_directory(self):
        """OpenCode v2 Session.directory is top-level, not location.directory."""
        st = json.loads((self.d / "state.json").read_text())
        st["lanes"]["voice"]["session_id"] = None
        session_list = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps([
                {"id": "ses_other", "directory": "/tmp/other"},
                {"id": "ses_voice", "directory": str(__import__("pathlib").Path.home() / "raphael-wt" / "voice")},
            ]), stderr="")
        active = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"data": {"ses_voice": {"type": "idle"}}}), stderr="")
        with mock.patch.object(coord_module.subprocess, "run",
                               side_effect=[session_list, active]) as run:
            sid = coord_module.find_session(self.d, "voice", st)
        self.assertEqual(sid, "ses_voice")
        self.assertEqual(st["lanes"]["voice"]["session_id"], "ses_voice")
        # SEC-1 PATH fix: coord resolves the opencode binary (shutil.which ->
        # ~/.opencode/bin/opencode fallback) so cron's minimal PATH works;
        # subprocess.run is called with the argv LIST as one positional arg.
        argv = run.call_args_list[0].args[0]
        self.assertTrue(argv[0].endswith("opencode"), argv[0])
        self.assertEqual(argv[1:4], ["session", "list", "--format"])

    def _fake_conductor(self) -> int:
        """Start a process whose /proc cmdline contains 'conductor'; return its pid."""
        p = subprocess.Popen(["bash", "-c", "exec -a conductor-fake sleep 30"])
        (self.d / "logs" / "conductor.pid").write_text(str(p.pid))
        return p.pid

    def test_mode_switching(self):
        # no conductor -> wait
        self.assertEqual(run(self.env, "mode", "--lane", "router").stdout.strip(), "wait")
        # conductor running -> exit
        pid = self._fake_conductor()
        try:
            self.assertEqual(run(self.env, "mode", "--lane", "router").stdout.strip(), "exit")
            # STOP armed -> wait
            (self.d / "STOP").touch()
            self.assertEqual(run(self.env, "mode", "--lane", "router").stdout.strip(), "wait")
            (self.d / "STOP").unlink()
            # paused lane -> wait even though conductor runs
            run(self.env, "reply", "--lane", "router", "--type", "pause", "--msg", "pause")
            st = json.loads((self.d / "state.json").read_text())
            st["lanes"]["router"]["paused"] = True
            (self.d / "state.json").write_text(json.dumps(st))
            self.assertEqual(run(self.env, "mode", "--lane", "router").stdout.strip(), "wait")
        finally:
            os.kill(pid, 9)
            os.waitpid(pid, 0)

    # ------------------------------------------------------------ wait
    def test_wait_wave_timeout_and_change(self):
        r = run(self.env, "wait", "--lane", "router", "--for", "wave", "--timeout", "1.5",
                expect=None)
        self.assertEqual(r.returncode, 1)   # spec: 1 on timeout
        th = threading.Thread(target=lambda: (
            time.sleep(0.6), run(self.env, "wave-bump", "--wave", "5")))
        th.start()
        r2 = run(self.env, "wait", "--lane", "router", "--for", "wave", "--timeout", "8")
        th.join()
        self.assertEqual(r2.returncode, 0)

    def test_wait_inbox_timeout_and_change(self):
        r = run(self.env, "wait", "--lane", "router", "--for", "inbox", "--timeout", "1",
                expect=None)
        self.assertEqual(r.returncode, 1)   # spec: 1 on timeout
        th = threading.Thread(target=lambda: (
            time.sleep(0.5), run(self.env, "reply", "--lane", "router",
                                 "--type", "nudge", "--msg", "wake")))
        th.start()
        r2 = run(self.env, "wait", "--lane", "router", "--for", "inbox", "--timeout", "8")
        th.join()
        self.assertEqual(r2.returncode, 0)

    # ------------------------------------------------------------ attention / notify
    def test_attention_appends_and_notify_fallback(self):
        run(self.env, "attention", "disk is full")
        att = (self.d / "ATTENTION.md").read_text()
        self.assertIn("disk is full", att)
        run(self.env, "notify", "fallback bell")
        self.assertIn("fallback bell", (self.d / "ATTENTION.md").read_text())

    # ------------------------------------------------------------ locks
    def test_hold_and_release(self):
        run(self.env, "hold", "--lane", "pc-control")
        time.sleep(0.5)
        out = json.loads(run(self.env, "status", "--json").stdout)
        self.assertEqual(out["lanes"]["pc-control"]["status"], "lock-held")
        run(self.env, "release", "--lane", "pc-control")
        time.sleep(0.5)
        out2 = json.loads(run(self.env, "status", "--json").stdout)
        self.assertNotEqual(out2["lanes"]["pc-control"]["status"], "lock-held")


class ConcurrentWriters(unittest.TestCase):
    """8 threads x 25 atomic appends must never tear a line."""

    def test_concurrent_posts_and_replies(self):
        env, d = fresh_env()
        try:
            subprocess.run([sys.executable, str(COORD), "init"], env=env, check=True,
                           capture_output=True)
            sys.path.insert(0, str(CONDUCTOR_DIR))
            import coord as coord_mod
            os.environ["RAPHAEL_COORD_DIR"] = str(d)
            n_threads, n_each = 8, 25
            errors: list[Exception] = []

            def worker(t: int):
                try:
                    for i in range(n_each):
                        if t % 2 == 0:
                            coord_mod.append_jsonl(
                                d / "events" / "router.jsonl",
                                {"ts": time.time(), "lane": "router", "type": "task_done",
                                 "wave": 2, "ref": None, "msg": f"t{t}-{i}", "data": None}, d)
                        else:
                            coord_mod.append_jsonl(
                                d / "inbox" / "brain-core.jsonl",
                                {"ts": time.time(), "lane": "brain-core", "type": "decision",
                                 "wave": 2, "ref": None, "msg": f"t{t}-{i}", "data": None}, d)
                except Exception as e:  # pragma: no cover
                    errors.append(e)

            threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            ev_lines = (d / "events" / "router.jsonl").read_text().splitlines()
            in_lines = (d / "inbox" / "brain-core.jsonl").read_text().splitlines()
            self.assertEqual(len(ev_lines), n_threads // 2 * n_each)
            self.assertEqual(len(in_lines), n_threads // 2 * n_each)
            msgs = set()
            for ln in ev_lines + in_lines:
                obj = json.loads(ln)          # raises if a line was torn/interleaved
                msgs.add(obj["msg"])
            expect = {f"t{t}-{i}" for t in range(n_threads) for i in range(n_each)}
            self.assertEqual(msgs, expect)     # exactly once, no loss, no dupes
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
