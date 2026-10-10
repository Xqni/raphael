#!/usr/bin/env python3
"""WSL-side leg of the Brain localhost relay.

Why this exists (verified 2026-10-05): the built-in Windows->WSL localhost
relay is blocked by the Hyper-V firewall on this machine (win->127.0.0.1:8765
= refused; win-><vm-ip>:8765 = connects). The Brain binds 127.0.0.1 per
PROTOCOL (localhost-only), so Windows clients cannot reach it directly either.

Chain:  [Windows client] 127.0.0.1:8765
          -> supervisor win-relay (user-space splice, 127.0.0.1 ONLY, no admin)
          -> <vm-ip>:8766 THIS helper (binds EXACTLY the VM NAT address)
          -> 127.0.0.1:8765 Brain (loopback, contract preserved)

BIND AUDIT (2026-10-06, network-security task):
  * This leg binds the VM's NAT IP — one specific address, NEVER a wildcard
    (the old NAT-or-wildcard fallback is gone: no NAT address -> exit 1).
  * It cannot bind 127.0.0.1: the Windows relay dials us over the vNIC and
    host->guest packets land on eth0, never on the guest loopback — and
    native Windows->WSL localhost forwarding is exactly what the Hyper-V
    firewall blocks here. The NAT address is host-internal (172.x NAT,
    not LAN-routable); the Brain itself never leaves loopback.
  * End-to-end 127.0.0.1 (helper not spawned at all) is available two ways:
    mirrored networking (supervisor auto-skips the relay) or the OPTIONAL
    narrow Hyper-V rule scripts/win/allow-brain-localhost.ps1
    (TCP 8765 for the WSL VM creator only — NOT the blanket
    -DefaultInboundAction Allow), then config paths.brain_relay: false.
    Details: scripts/NETWORK-SECURITY.md.

Stdlib only; runs on the system python3; spawned by supervisor/main.py
(detached, hidden) and lives across supervisor restarts until WSL shuts down.

Usage: wsl-relay.py [listen_port=8766] [dial_port=8765]
Exit codes: 0 ok, 1 no NAT address (refuses wildcard bind).
"""
import os
import select
import socket
import sys
import threading
import time

LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
DIAL_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8765

# SEC-6: idle cap >= 3x the PROTOCOL 10 s WS ping (default 90 s) — a
# pinging peer never reaches it; a silently-dead peer is reaped.
# Override: RAPHAEL_RELAY_IDLE_CAP (seconds; tests use small values).
try:
    IDLE_CAP = float(os.environ.get("RAPHAEL_RELAY_IDLE_CAP", "90"))
except ValueError:
    IDLE_CAP = 90.0


def set_keepalive(sock):
    """SEC-6: TCP keepalive (OS-level dead-peer detection ~30s+3x1s).
    Never raises."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        return
    for opt_name, value in (("TCP_KEEPIDLE", 30), ("TCP_KEEPINTVL", 3),
                            ("TCP_KEEPCNT", 3)):
        opt = getattr(socket, opt_name, None)
        if opt is None:
            continue
        try:
            sock.setsockopt(socket.IPPROTO_TCP, opt, value)
        except OSError:
            pass


def pipe(src, dst, idle_cap=None):
    """Splice with an idle cap (SEC-6): forward until EOF; close a leg
    silent for longer than `idle_cap`. select() keeps healthy streams
    blocking-forever semantics between checks (a short recv timeout would
    tear down legitimate WS silence — see the header note) while the
    deadline still fires. Connection cap stays with the accept loop."""
    cap = IDLE_CAP if idle_cap is None else float(idle_cap)
    last = time.monotonic()
    try:
        while True:
            remaining = cap - (time.monotonic() - last)
            if remaining <= 0:
                print("[wsl-relay] idle cap %.0fs reached — reaping silent "
                      "peer" % cap, flush=True)
                break
            try:
                readable, _, _ = select.select([src], [], [],
                                               min(remaining, 1.0))
            except (OSError, ValueError):
                break
            if not readable:
                continue
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
            last = time.monotonic()
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(client):
    set_keepalive(client)                       # SEC-6
    try:
        backend = socket.create_connection(("127.0.0.1", DIAL_PORT), timeout=5)
        # CRITICAL: the connect timeout PERSISTS as the socket's recv timeout
        # — a relayed WS stream is silent for ~10s between server pings, so
        # recv() would time out and tear the connection down ("no close frame
        # received or sent" drops at ~5-9s). Reset to blocking after connect;
        # the SEC-6 select()-based idle cap below owns staleness instead.
        backend.settimeout(None)
        set_keepalive(backend)                  # SEC-6
    except OSError:
        try:
            client.close()
        except OSError:
            pass
        return
    threading.Thread(target=pipe, args=(client, backend), daemon=True).start()
    pipe(backend, client)
    for sock in (client, backend):
        try:
            sock.close()
        except OSError:
            pass


MAX_CONN = 64  # security: bounded concurrent splices (local-only flood guard)
_slots = threading.BoundedSemaphore(MAX_CONN)


def _local_ips():
    """All IPv4s of this WSL VM (security: bind ONE of them, never all)."""
    try:
        import subprocess
        out = subprocess.run(["hostname", "-I"], capture_output=True,
                             text=True, timeout=5).stdout
        return [tok for tok in out.split() if tok.count(".") == 3]
    except Exception:
        return []


def _nat_ip():
    """First IPv4 of this WSL VM (security: bind the NAT address, not all)."""
    ips = _local_ips()
    return ips[0] if ips else None


def bind_check_interval():
    try:
        return float(os.environ.get("RAPHAEL_RELAY_BIND_CHECK", "300"))
    except ValueError:
        return 300.0


def bind_still_valid(bind_ip, get_ips=None):
    """Design-review finding 12: the helper binds its NAT IP once and lives
    until WSL shutdown — if the address is ever rebound away, the bind goes
    stale. Re-resolve and report; EXIT path is safe ONLY because the
    supervisor watchdog (finding 3) now respawns us with a fresh address."""
    ips = (get_ips or _local_ips)()
    return bind_ip in ips


def bind_watch_loop(bind_ip, srv, get_ips=None, nap=None, stop=None,
                    interval=None):
    """Periodically re-check the bind address (default every
    RAPHAEL_RELAY_BIND_CHECK=300 s). Address gone -> close the listener:
    the accept loop sees fileno()==-1, exits cleanly (the zombie-guard
    semantics), the process ends, and the supervisor watchdog respawns a
    helper bound to the fresh address."""
    nap = nap or time.sleep
    stop = stop or (lambda: False)
    interval = bind_check_interval() if interval is None else float(interval)
    while True:
        waited = 0.0
        while waited < interval and not stop():
            step = min(5.0, interval - waited)
            nap(step)
            waited += step
        if stop():
            return
        if not bind_still_valid(bind_ip, get_ips):
            print("[wsl-relay] bind address %s vanished from this host — "
                  "closing listener for watchdog respawn (finding 12)"
                  % bind_ip, flush=True)
            try:
                srv.close()
            except OSError:
                pass
            return


def _serve(client):
    try:
        handle(client)
    finally:
        _slots.release()


def resolve_bind_addr(ip):
    """EXACTLY ONE address: the VM NAT IP. Returns None instead of ever
    falling back to a wildcard (0.0.0.0) bind — see the header BIND AUDIT."""
    return ip or None


def main():
    ip = resolve_bind_addr(_nat_ip())
    if not ip:
        print("[wsl-relay] FATAL: cannot determine the VM NAT address "
              "(hostname -I) — refusing to bind 0.0.0.0; exiting",
              flush=True)
        return 1
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((ip, LISTEN_PORT))          # one specific address, never wildcard
    srv.listen(128)
    print("[wsl-relay] %s:%d -> 127.0.0.1:%d" % (ip, LISTEN_PORT,
                                                 DIAL_PORT), flush=True)
    threading.Thread(target=bind_watch_loop, args=(ip, srv), daemon=True).start()
    accept_loop(srv)
    return 0


def accept_loop(srv):
    """Resilient accept loop — ported from the Windows leg's
    zombie-listener guard (supervisor/main.py, incident 2026-10-08; this
    helper stayed bare and died on the FIRST transient OSError, and with
    one spawn per bring-up and no watchdog the whole chain went dark until
    a manual rescue — recurring wedges 2026-10-08 AND 2026-10-09,
    design-review finding 3).

    Semantics (identical to the Windows leg): a transient accept OSError
    is LOGGED and the loop CONTINUES while the bound socket lives; only
    `fileno() == -1` (socket really gone) ends the loop. The connection
    semaphore and thread-per-connection model are unchanged."""
    while True:
        try:
            client, _addr = srv.accept()
        except OSError as exc:
            if srv.fileno() == -1:
                print("[wsl-relay] listener closed — accept loop exiting",
                      flush=True)
                return
            print("[wsl-relay] transient accept OSError (%s) — continuing"
                  % exc, flush=True)
            time.sleep(0.1)
            continue
        if not _slots.acquire(blocking=False):
            try:
                client.close()
            except OSError:
                pass
            continue  # security: connection cap reached, shed load
        threading.Thread(target=_serve, args=(client,), daemon=True).start()


if __name__ == "__main__":
    sys.exit(main())
