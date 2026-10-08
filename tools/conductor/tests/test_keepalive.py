#!/usr/bin/env python3
"""Keepalive tests — dispatch decisions + usage/reset state machine. No network/models.

Run: python3 tools/conductor/tests/test_keepalive.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
CDIR = HERE.parent
sys.path.insert(0, str(CDIR))

import keepalive  # noqa: E402


class KBase(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="keepalive-test-"))
        self._old_cd = keepalive.CD
        keepalive.CD = self.d
        for lane in keepalive.LANES:
            (self.d / "events").mkdir(parents=True, exist_ok=True)
            (self.d / "inbox").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        keepalive.CD = self._old_cd

    def write_state(self, cursors, lanes=None, **extra):
        st = {"cursors": cursors, "lanes": lanes or {}, **extra}
        (self.d / "state.json").write_text(json.dumps(st))
        return st


class TestUsageMath(KBase):
    def test_cost_and_windows_are_value_blind_and_correct(self):
        now = datetime.now(timezone.utc)
        rows = [
            {"timestamp": (now - timedelta(minutes=10)).isoformat(),
             "provider": "go", "model": "mimo-v2.5",
             "tokens_input": 1_000_000, "tokens_output": 1_000_000, "outcome": "success"},
            {"timestamp": (now - timedelta(days=5)).isoformat(),   # in-month, in-week, outside 5h
             "provider": "go", "model": "mimo-v2.5",
             "tokens_input": 1_000_000, "tokens_output": 0, "outcome": "success"},
            {"timestamp": (now - timedelta(minutes=5)).isoformat(),
             "provider": "groq", "model": "whisper",   # not Go spend
             "tokens_input": 5_000_000, "tokens_output": 0, "outcome": "success"},
            {"timestamp": (now - timedelta(minutes=5)).isoformat(),
             "provider": "go", "model": "deepseek-v4-flash",
             "tokens_input": 0, "tokens_output": 0, "outcome": "failure",
             "error_code": "FreeUsageLimitError"},
        ]
        tot = keepalive.window_totals(rows)
        # mimo: 0.14 in + 0.28 out => 0.42 USD for the recent row; 10-day-old row
        # (0.14) counts weekly+monthly but not 5h; groq excluded everywhere.
        self.assertAlmostEqual(tot["windows"]["five_h"], 0.42, places=6)
        self.assertAlmostEqual(tot["windows"]["weekly"], 0.56, places=6)  # 5d-old row inside week+month, outside 5h
        self.assertAlmostEqual(tot["windows"]["monthly"], 0.56, places=6)
        self.assertEqual(len(tot["hits"]), 1)
        # never emits token/secret material, only aggregate USD
        snap = json.dumps(tot)
        self.assertNotIn("whisper-large", snap)

    def test_hit_state_roundtrip_and_budget_defaults(self):
        keepalive.STATE_FILE = self.d / "usage-watch.json"
        st = keepalive.load_state()
        self.assertEqual(st["budgets"], keepalive.DEFAULT_BUDGETS)
        self.assertIsNone(st["go_hit"])
        st["go_hit"] = {"ts": 1.0, "provider": "go", "reason": "x"}
        keepalive.save_state(st)
        st2 = keepalive.load_state()
        self.assertEqual(st2["go_hit"]["provider"], "go")


class TestDispatchLogic(KBase):
    def test_inactive_lane_with_pending_is_pinged(self):
        lanes = {ln: {"session_id": f"ses_{ln}", "last_ping": 0} for ln in keepalive.LANES}
        lanes["voice"]["paused"] = True          # paused lanes never pinged
        st = self.write_state({"infra": 19, "voice": 0}, lanes=lanes,
                              integrator_last_ping=9_999.9)  # infra pending=1; integrator quiet
        (self.d / "events" / "infra.jsonl").write_text("\n".join(
            json.dumps({"type": "heartbeat"}) for _ in range(20)) + "\n")
        (self.d / "inbox" / "voice.jsonl").write_text(json.dumps({"type": "nudge"}) + "\n")
        (self.d / "inbox" / "voice.read").write_text("1")
        pings = []
        with mock.patch.object(keepalive, "ping", side_effect=lambda ln, m: pings.append(ln) or True), \
             mock.patch.object(keepalive, "active_sessions", return_value=set()), \
             mock.patch.object(keepalive, "ensure_conductor", lambda st: None), \
             mock.patch.object(keepalive, "time") as tm:
            tm.time.return_value = 10_000.0
            keepalive.cmd_dispatch()
        self.assertEqual(pings, ["infra"])        # paused voice excluded; others idle w/o pending

    def test_active_lane_and_recent_ping_are_not_pinged(self):
        lanes = {ln: {"session_id": "ses_x", "last_ping": 9_999} for ln in keepalive.LANES}
        st = self.write_state({"infra": 0}, lanes=lanes,
                              integrator_last_ping=10_000.0)
        (self.d / "events" / "infra.jsonl").write_text(json.dumps({"type": "e"}) + "\n")
        pings = []
        with mock.patch.object(keepalive, "ping", side_effect=lambda ln, m: pings.append(ln) or True), \
             mock.patch.object(keepalive, "active_sessions", return_value={"ses_x"}), \
             mock.patch.object(keepalive, "ensure_conductor", lambda st: None), \
             mock.patch.object(keepalive, "time") as tm:
            tm.time.return_value = 10_000.0
            keepalive.cmd_dispatch()   # active session + integrator cooldown fresh
        self.assertEqual(pings, [])

    def test_dispatch_never_rewrites_state_json(self):
        """Regression 2026-10-08: a whole-state write reverted every cursor."""
        st = self.write_state({"infra": 3}, {ln: {"last_ping": 0} for ln in keepalive.LANES})
        before = (self.d / "state.json").read_bytes()
        (self.d / "events" / "infra.jsonl").write_text(json.dumps({"type": "e"}) + "\n")
        with mock.patch.object(keepalive, "ping", return_value=True), \
             mock.patch.object(keepalive, "active_sessions", return_value=set()), \
             mock.patch.object(keepalive, "ensure_conductor", lambda st: None):
            keepalive.cmd_dispatch()
        self.assertEqual((self.d / "state.json").read_bytes(), before,
                         "keepalive must never rewrite state.json (cursor revert incident)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
