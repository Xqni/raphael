# -*- coding: utf-8 -*-
"""Instance isolation derivation — docs/INTERFACES.md §(d).

Single source of truth for the supervisor AND the `raphael` CLI: the
`RAPHAEL_INSTANCE` env var derives the REST/WS port, the single-instance
mutex name, the brain pidfile(s) (WSL side), the Body single-instance lock
(Windows side), the supervisor pidfile, and per-instance log file names.
Code reads these helpers — never a hardcoded port/lock/path (AGENT_RULES §5).

CONTRACT: `RAPHAEL_INSTANCE` unset or `main` == today's exact behavior.
Every main value below is byte-identical to the historical hardcoded one,
with ONE deliberate change (session brief task 3): the brain pidfile moves
out of world-writable /tmp into the per-user data dir
(`~/.raphael/brain.pid`). The legacy `/tmp/raphael-brain.pid` is ALWAYS
carried as a read/remove fallback until brain/app.py adopts the new path
(docs/requests/infra__to__brain-core__pidfile-location.md), so a running
stack is never orphaned mid-migration.

Derived-name format (INTERFACES §d): `<main-name>_<instance>` for
mutex/pidfile/lock/log suffixes; `8900 + lane index` for ports (main keeps
8765); `~/.raphael/<instance>/` for the WSL-side data dir.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Lane order from INTERFACES §d — the port table is positional:
# router=8901 ... evolution-persona=8910. main is special (8765).
INSTANCE_ORDER = (
    "main", "router", "brain-core", "pc-control", "voice",
    "computer-use", "orb", "infra", "qa-security", "tools-memory",
    "evolution-persona",
)

MAIN_PORT = 8765
MAIN_MUTEX = "Raphael_Supervisor"
MAIN_BODY_LOCK = "raphael_body.lock"
MAIN_WSL_PIDFILE = "~/.raphael/brain.pid"           # new, proper location
LEGACY_WSL_PIDFILE = "/tmp/raphael-brain.pid"       # pre-migration fallback

# The instance name is interpolated into shell strings, file paths and a
# Win32 mutex name — strip anything outside the safe charset up front.
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def instance_name(raw=None) -> str:
    """Sanitized instance name; unset/empty -> 'main'.

    Unsafe characters are stripped ('../../etc' -> 'etc') because the name
    lands in sh strings and paths. Callers that care about a silent fixup
    compare against the raw env value themselves.
    """
    if raw is None:
        raw = os.environ.get("RAPHAEL_INSTANCE", "")
    name = str(raw).strip() or "main"
    cleaned = _UNSAFE.sub("", name)
    return cleaned or "main"


def is_main(inst=None) -> bool:
    return (inst or instance_name()) == "main"


def known_instance(inst=None) -> bool:
    inst = inst or instance_name()
    return inst in INSTANCE_ORDER


def instance_port(inst=None, default=None) -> int:
    """Derived REST/WS port.

    Precedence (INTERFACES §c.4): explicit RAPHAEL_PORT wins; main -> caller
    default (config port, 8765); known lane -> 8900 + index; unknown ->
    caller default (isolating an unknown instance is the caller's job —
    set RAPHAEL_PORT explicitly).
    """
    env = os.environ.get("RAPHAEL_PORT")
    if env:
        try:
            return int(str(env).strip())
        except ValueError:
            pass
    inst = inst or instance_name()
    if inst in INSTANCE_ORDER and inst != "main":
        return 8900 + INSTANCE_ORDER.index(inst)
    try:
        return int(default) if default is not None else MAIN_PORT
    except (TypeError, ValueError):
        return MAIN_PORT


def mutex_name(inst=None) -> str:
    """Named mutex (INTERFACES §d): `Raphael_Supervisor[_<instance>]`.

    Single source with the Body (approved pc-control request, 2026-10-06):
    when `inst` is not given explicitly, reuse
    `body/win/instance.py::supervisor_mutex()` — the shared derivation the
    Body calls too, so supervisor and Body can never disagree on the mutex
    name. The import is best-effort: pre-merge trees, or an env their
    stricter validator rejects (their `instance_name()` raises by design),
    fall back to the mirror below, which is byte-identical for every valid
    name. Explicit `inst` always uses the mirror (their function reads the
    environment itself).
    """
    if inst is None:
        shared = _shared_supervisor_mutex()
        if shared is not None:
            return shared
    inst = inst or instance_name()
    return MAIN_MUTEX if inst == "main" else "%s_%s" % (MAIN_MUTEX, inst)


def _shared_supervisor_mutex():
    """body/win/instance.py::supervisor_mutex, or None if unavailable."""
    root = str(repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from body.win.instance import supervisor_mutex
        return supervisor_mutex()
    except Exception:      # noqa: BLE001 — never let the logon entry point die
        return None


def health_url(port=None) -> str:
    if port is None:
        port = instance_port()
    return "http://127.0.0.1:%d/health" % int(port)


def wsl_data_dir(inst=None) -> str:
    """WSL-side data dir ('~' expands in every sh we spawn)."""
    inst = inst or instance_name()
    return "~/.raphael" if inst == "main" else "~/.raphael/%s" % inst


def wsl_pidfiles(inst=None):
    """[new proper path, legacy /tmp path] — always both, new first.

    supervisor writes the new path at spawn; brain/app.py still writes the
    legacy one until brain-core adopts the request. Recycle code reads both
    (cmdline-verified) and removes both.
    """
    inst = inst or instance_name()
    if inst == "main":
        return [MAIN_WSL_PIDFILE, LEGACY_WSL_PIDFILE]
    return ["~/.raphael/%s/brain.pid" % inst,
            "/tmp/raphael-brain_%s.pid" % inst]


def body_lock_name(inst=None) -> str:
    inst = inst or instance_name()
    return MAIN_BODY_LOCK if inst == "main" else "raphael_body_%s.lock" % inst


def supervisor_pidfile(inst=None, root=None) -> Path:
    """run/supervisor[_<inst>].pid (repo runtime dir, gitignored)."""
    inst = inst or instance_name()
    name = "supervisor.pid" if inst == "main" else "supervisor_%s.pid" % inst
    return (Path(root) if root else repo_root()) / "run" / name


def log_path(name, inst=None, root=None) -> Path:
    """logs/<name>.log (main — unchanged) / logs/<name>_<inst>.log."""
    inst = inst or instance_name()
    file_name = "%s.log" % name if inst == "main" else "%s_%s.log" % (name, inst)
    return (Path(root) if root else repo_root()) / "logs" / file_name


def relay_backend_port(listen_port) -> int:
    """WSL helper-leg port (Windows dials the WSL NAT IP on this port).

    main keeps the historical 8766; instances use port+1000 so no helper
    can ever shadow another lane's brain port (helper listens on the NAT
    IP, brains listen on loopback — but two helpers would bind-clash and
    cross-route if this overlapped).
    """
    listen_port = int(listen_port)
    return 8766 if listen_port == MAIN_PORT else listen_port + 1000
