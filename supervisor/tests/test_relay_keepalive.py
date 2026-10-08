"""SEC-6 — relay keepalive + idle-cap (fast suite). Proves: silent peers
are reaped, pinging peers survive, keepalive flags land, the connection
semaphore is kept, and the >= 3x-ping cap default (90 s) holds. The REAL-
duration proof lives in test_relay_keepalive_long.py (env-gated)."""
import importlib.util
import socket
import sys
import threading
import time
from pathlib import Path

from supervisor import main as sup

_ROOT = Path(__file__).resolve().parents[2]


def _load_wsrelay():
    path = _ROOT / "scripts" / "wsl-relay.py"
    spec = importlib.util.spec_from_file_location("wslrelay_keeptest", path)
    mod = importlib.util.module_from_spec(spec)
    old_argv = sys.argv
    sys.argv = ["wsl-relay.py"]                # argv parsed at import time
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = old_argv
    return mod


def test_silent_peer_is_reaped():
    a, b = socket.socketpair()
    done = threading.Event()

    def run():
        sup.relay_pipe(a, b, idle_cap=0.8)
        done.set()

    threading.Thread(target=run, daemon=True).start()
    assert done.wait(timeout=4.0), "silent peer was NOT reaped"
    a.close()
    b.close()


def test_pinging_peer_survives_beyond_cap():
    a, b = socket.socketpair()          # pinger writes b -> readable on a
    sink, _drain = socket.socketpair()  # pipe writes HERE (no echo loop:
                                        # a self-fed pipe would never idle)
    stop = threading.Event()
    pipe_alive = threading.Event()

    def pipe_run():
        pipe_alive.set()
        sup.relay_pipe(a, sink, idle_cap=0.8)   # cap 0.8 s ...
        pipe_alive.clear()

    def pinger():
        # ... while pings arrive every 0.25 s (scaled 10 s ping): survive
        while not stop.is_set():
            try:
                b.sendall(b"ping")
            except OSError:
                return
            time.sleep(0.25)

    threading.Thread(target=pipe_run, daemon=True).start()
    ping = threading.Thread(target=pinger, daemon=True)
    ping.start()
    time.sleep(2.2)                            # >2.5x the cap, with traffic
    assert pipe_alive.is_set(), "pinging peer was wrongly reaped"
    stop.set()
    ping.join(timeout=3)
    # after pings stop the idle cap must still close it (reap correctness)
    deadline = time.monotonic() + 4
    while pipe_alive.is_set() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not pipe_alive.is_set()
    for s in (a, b, sink, _drain):
        s.close()


def test_keepalive_flag_landed():
    a, b = socket.socketpair()
    try:
        sup._set_socket_keepalive(a)
        assert a.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 1
        mod = _load_wsrelay()
        mod.set_keepalive(b)
        assert b.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 1
    finally:
        a.close()
        b.close()


def test_default_idle_cap_is_at_least_3x_ping(monkeypatch):
    # PROTOCOL WS ping = 10 s -> cap >= 90 s
    monkeypatch.delenv("RAPHAEL_RELAY_IDLE_CAP", raising=False)
    assert sup._relay_idle_cap() == 90.0
    assert sup._relay_idle_cap() >= 3 * 10
    monkeypatch.setenv("RAPHAEL_RELAY_IDLE_CAP", "120")
    assert sup._relay_idle_cap() == 120.0
    monkeypatch.setenv("RAPHAEL_RELAY_IDLE_CAP", "junk")
    assert sup._relay_idle_cap() == 90.0        # fail-safe default
    src = (_ROOT / "scripts" / "wsl-relay.py").read_text()
    assert 'os.environ.get("RAPHAEL_RELAY_IDLE_CAP", "90")' in src


def test_connection_semaphore_kept_on_both_legs():
    # the audit requires KEEPING the connection-limit semaphore
    helper = (_ROOT / "scripts" / "wsl-relay.py").read_text()
    main_src = (_ROOT / "supervisor" / "main.py").read_text()
    assert "BoundedSemaphore" in helper
    assert "BoundedSemaphore" in main_src
    # Windows leg splices through the shared capped pipe + keepalive
    assert "target=relay_pipe" in main_src
    assert "_set_socket_keepalive(client)" in main_src
    # the deliberate blocking behavior for HEALTHY streams stays
    assert "backend.settimeout(None)" in helper
    assert "backend.settimeout(None)" in main_src
