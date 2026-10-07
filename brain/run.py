"""Entry point for raphael-brain.service (and the documented systemd path):
resolves the bind host per PROTOCOL §1 + the network-security fix, then runs
uvicorn on brain.app:app.

Overrides (explicit env wins, docs/INTERFACES.md §c):
  RAPHAEL_BIND     bind-host escape hatch (e.g. 0.0.0.0 only when the
                   user-space relay is disabled AND native WSL localhost
                   forwarding is verified — see scripts/NETWORK-SECURITY.md)
  RAPHAEL_PORT     listen port (supervisor exports it for process mode)
  RAPHAEL_INSTANCE -> port derivation via supervisor/instance.py (§d)
  RAPHAEL_LOG_LEVEL

Default host: **127.0.0.1 in BOTH networking modes** (network-security fix,
2026-10-06 — "bind loopback wherever the networking mode allows"):
  * mirrored: Windows shares the same loopback natively.
  * NAT: every Windows client reaches the Brain through the supervisor's
    user-space relay, whose WSL helper leg dials 127.0.0.1 inside the VM;
    WSL-internal clients (orb, tests, Fish TTS) already use loopback. The
    supervisor's process-mode spawn has always used --host 127.0.0.1 and
    that is exactly what the live Wave-2 e2e ran with.
  * WSL's localhostForwarding covers ports "bound to wildcard or localhost"
    in the VM, so once the OPTIONAL narrow Hyper-V rule
    (scripts/win/allow-brain-localhost.ps1 — TCP 8765 for the WSL VM
    creator only) is applied, even native Windows->localhost works and the
    relay can be switched off (config paths.brain_relay: false).
"""
import os
import sys

import uvicorn

# Repo root FIRST on sys.path so this works as `python -m brain.run`, as
# `python brain/run.py`, and under systemd — and so the repo's own
# `supervisor` package (regular package: __init__.py present) wins over any
# same-named site package (regular packages beat namespace portions only by
# sys.path order).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    sys.path.remove(_ROOT)
except ValueError:
    pass
sys.path.insert(0, _ROOT)

from supervisor.instance import instance_name, instance_port  # noqa: E402


def detect_host() -> str:
    override = os.environ.get('RAPHAEL_BIND')
    if override:
        return override
    return '127.0.0.1'   # loopback default — rationale in the module docstring


def detect_port() -> int:
    # RAPHAEL_PORT wins; otherwise derive from RAPHAEL_INSTANCE (§d);
    # main/unset -> 8765 (historical default, zero change).
    return instance_port(instance_name(), default=8765)


def main():
    host = detect_host()
    port = detect_port()
    log_level = os.environ.get('RAPHAEL_LOG_LEVEL', 'info')
    uvicorn.run('brain.app:app', host=host, port=port, log_level=log_level)


if __name__ == '__main__':
    main()
