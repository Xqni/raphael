"""SEC-6 REAL-DURATION proof (env-gated — skipped in normal runs):
  1. a silent peer is reaped at the REAL 90 s idle cap;
  2. a pinging peer (10 s interval = the PROTOCOL WS ping) survives a
     full 5+ MINUTES against that same cap.

Run explicitly (Rule 14: alone, nothing else in parallel):
  RAPHAEL_LONG_TESTS=1 tests/.venv/bin/python -m pytest -q \
      supervisor/tests/test_relay_keepalive_long.py
"""
import os
import socket
import threading
import time

import pytest

from supervisor import main as sup

pytestmark = pytest.mark.skipif(
    not os.environ.get("RAPHAEL_LONG_TESTS"),
    reason="SEC-6 long proof — set RAPHAEL_LONG_TESTS=1 (~6.5 min)")


def test_silent_peer_reaped_at_real_90s_cap():
    a, b = socket.socketpair()
    done = threading.Event()
    t0 = time.monotonic()

    def run():
        sup.relay_pipe(a, b, idle_cap=90.0)    # REAL cap
        done.set()

    threading.Thread(target=run, daemon=True).start()
    assert done.wait(timeout=110.0), "silent peer survived past the 90s cap"
    elapsed = time.monotonic() - t0
    assert 85.0 <= elapsed <= 100.0, "reaped at %.1fs (want ~90)" % elapsed
    a.close()
    b.close()


def test_pinging_peer_survives_five_minutes():
    a, b = socket.socketpair()          # pinger writes b -> readable on a
    sink, _drain = socket.socketpair()  # pipe destination (NO echo loop:
                                        # a self-fed pipe never goes idle)
    stop = threading.Event()
    pipe_done = threading.Event()
    sent = {"n": 0}

    def pipe_run():
        sup.relay_pipe(a, sink, idle_cap=90.0)
        pipe_done.set()

    def pinger():
        # 10 s interval — exactly the PROTOCOL server ping cadence
        while not stop.is_set():
            try:
                b.sendall(b"ping-frame")
            except OSError:
                return
            sent["n"] += 1
            time.sleep(10.0)

    threading.Thread(target=pipe_run, daemon=True).start()
    threading.Thread(target=pinger, daemon=True).start()
    deadline = time.monotonic() + 300.0        # 5 MINUTES
    while time.monotonic() < deadline:
        assert not pipe_done.is_set(), (
            "pinging peer was reaped early (survived only %.0fs)"
            % (300.0 - (deadline - time.monotonic())))
        time.sleep(1.0)
    stop.set()
    assert sent["n"] >= 28, "pinger only sent %d frames" % sent["n"]
    assert not pipe_done.is_set(), "pipe died during the 5-minute window"
    # and it still reaps once pings stopped (idle cap correctness end-to-end)
    assert pipe_done.wait(timeout=100.0), "no reap after pings stopped"
    for s in (a, b, sink, _drain):
        s.close()
