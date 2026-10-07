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
import socket
import sys
import threading

LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
DIAL_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8765


def pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(client):
    try:
        backend = socket.create_connection(("127.0.0.1", DIAL_PORT), timeout=5)
        # CRITICAL: the connect timeout PERSISTS as the socket's recv timeout
        # — a relayed WS stream is silent for ~10s between server pings, so
        # recv() would time out and tear the connection down ("no close frame
        # received or sent" drops at ~5-9s). Reset to blocking after connect.
        backend.settimeout(None)
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


def _nat_ip():
    """First IPv4 of this WSL VM (security: bind the NAT address, not all)."""
    try:
        import subprocess
        out = subprocess.run(["hostname", "-I"], capture_output=True,
                             text=True, timeout=5).stdout
        for tok in out.split():
            if tok.count(".") == 3:
                return tok
    except Exception:
        pass
    return None


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
    while True:
        client, _addr = srv.accept()
        if not _slots.acquire(blocking=False):
            try:
                client.close()
            except OSError:
                pass
            continue  # security: connection cap reached, shed load
        threading.Thread(target=_serve, args=(client,), daemon=True).start()


if __name__ == "__main__":
    sys.exit(main())
