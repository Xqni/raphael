#!/usr/bin/env python3
"""WSL-side leg of the Brain localhost relay.

Why this exists (verified 2026-10-05): the built-in Windows->WSL localhost
relay is blocked by the Hyper-V firewall on this machine (win->127.0.0.1:8765
= refused; win-><vm-ip>:8765 = connects). The Brain binds 127.0.0.1 per
PROTOCOL (localhost-only), so Windows clients cannot reach it directly either.

Chain:  [Windows client] 127.0.0.1:8765
          -> supervisor win-relay (user-space splice, no admin)
          -> <vm-ip>:8766 THIS helper (binds 0.0.0.0 inside the WSL NAT)
          -> 127.0.0.1:8765 Brain (loopback, contract preserved)

Privacy: binds 0.0.0.0 only on the WSL NAT interface (vm-ip), which is not
routable from the LAN; the Brain itself never leaves loopback. The single
machine-local intent of "localhost-only" is preserved end to end.

Stdlib only; runs on the system python3; spawned by supervisor/main.py
(detached, hidden) and lives across supervisor restarts until WSL shuts down.

Usage: wsl-relay.py [listen_port=8766] [dial_port=8765]
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


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ip = _nat_ip()
    srv.bind((ip or "0.0.0.0", LISTEN_PORT))  # security: NAT addr, not all-ifaces
    srv.listen(128)
    print("[wsl-relay] %s:%d -> 127.0.0.1:%d" % (ip or "0.0.0.0", LISTEN_PORT,
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
    main()
