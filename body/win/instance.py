"""Instance isolation for the Windows Body (INTERFACES §d, AGENT_RULES §5).

`RAPHAEL_INSTANCE` (unset or `main` = today's exact behavior, zero change)
derives every per-instance resource so two stacks never collide:

| resource     | main (unset)                  | instance `<lane>`                    |
|--------------|-------------------------------|--------------------------------------|
| WS/REST port | 8765 (PROTOCOL §1)            | 8901-8910 (INTERFACES §d table)      |
| body lock    | `%TMP%\\raphael_body.lock`    | `%TMP%\\raphael_body_<lane>.lock`    |
| token        | `%APPDATA%\\Raphael\\token` then `~/.raphael/token` | `%APPDATA%\\Raphael\\<lane>\\token` then `~/.raphael/<lane>/token` |
| data dir     | `~/.raphael/`                 | `~/.raphael/<lane>/`                 |
| action log   | `logs/actions.log`            | `logs/actions_<lane>.log`            |
| supervisor mutex | `Raphael_Supervisor`       | `Raphael_Supervisor_<lane>`          |

Env overrides (all optional): `RAPHAEL_PORT` (port, honored by brain/run.py
too), `RAPHAEL_TOKEN_PATH` (token, existing brain/auth.py convention),
`RAPHAEL_ACTION_LOG` (action-log path, tests).

Call the functions — nothing is captured at import time, so tests can flip
the environment freely.
"""
from __future__ import annotations

import os
import pathlib
import re
from typing import List

_MAIN = "main"
# Lane names come from OWNERSHIP/WAVES; keep them filesystem/WS-safe.
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}\Z")

# INTERFACES §d: instance -> WS/REST port. main is fixed at 8765 (PROTOCOL §1).
_LANE_PORTS = {
    "router": 8901,
    "brain-core": 8902,
    "pc-control": 8903,
    "voice": 8904,
    "computer-use": 8905,
    "orb": 8906,
    "infra": 8907,
    "qa-security": 8908,
    "tools-memory": 8909,
    "evolution-persona": 8910,
}


def instance_name() -> str:
    """Active instance name; unset/empty = `main` (today's behavior)."""
    raw = os.environ.get("RAPHAEL_INSTANCE", "").strip()
    name = raw or _MAIN
    if not _NAME_RE.match(name):
        raise ValueError(
            "invalid RAPHAEL_INSTANCE %r (allowed: letters/digits/_/-, "
            "must start alphanumeric, max 32 chars)" % raw)
    return name


def is_main() -> bool:
    return instance_name() == _MAIN


def port() -> int:
    """WS/REST port for this instance. Never guesses: unknown instance
    without RAPHAEL_PORT raises (AGENT_RULES §5 — never default a port)."""
    env = os.environ.get("RAPHAEL_PORT", "").strip()
    if env:
        try:
            p = int(env)
        except ValueError:
            raise ValueError("RAPHAEL_PORT must be an integer, got %r" % env)
        if not (1 <= p <= 65535):
            raise ValueError("RAPHAEL_PORT out of range: %d" % p)
        return p
    name = instance_name()
    if name == _MAIN:
        return 8765
    try:
        return _LANE_PORTS[name]
    except KeyError:
        raise ValueError(
            "unknown RAPHAEL_INSTANCE %r — set RAPHAEL_PORT explicitly "
            "(INTERFACES §d)" % name)


def ws_url() -> str:
    return "ws://127.0.0.1:%d/ws" % port()


def body_lock_path() -> pathlib.Path:
    # os.getenv('TMP', '/tmp') is byte-for-byte the original main behavior.
    base = pathlib.Path(os.getenv("TMP", "/tmp"))
    name = ("raphael_body.lock" if is_main()
            else "raphael_body_%s.lock" % instance_name())
    return base / name


def token_candidates() -> List[pathlib.Path]:
    """Ordered token search path — strictly per instance (a lane body must
    never fall back to the main token or vice versa)."""
    out: List[pathlib.Path] = []
    envp = os.environ.get("RAPHAEL_TOKEN_PATH", "").strip()
    if envp:
        out.append(pathlib.Path(envp))
    name = instance_name()
    appdata = os.environ.get("APPDATA", "")
    if name == _MAIN:
        if appdata:
            out.append(pathlib.Path(appdata) / "Raphael" / "token")
        out.append(pathlib.Path.home() / ".raphael" / "token")
    else:
        if appdata:
            out.append(pathlib.Path(appdata) / "Raphael" / name / "token")
        out.append(pathlib.Path.home() / ".raphael" / name / "token")
    return out


def data_dir() -> pathlib.Path:
    root = pathlib.Path.home() / ".raphael"
    return root if is_main() else root / instance_name()


def action_log_path() -> pathlib.Path:
    """PROTOCOL §7 action log: logs/actions.log (main) /
    logs/actions_<instance>.log (isolated instances)."""
    env = os.environ.get("RAPHAEL_ACTION_LOG", "").strip()
    if env:
        return pathlib.Path(env)
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    name = "actions.log" if is_main() else "actions_%s.log" % instance_name()
    return repo_root / "logs" / name


def supervisor_mutex() -> str:
    """Named mutex for the supervisor (INTERFACES §d table). The supervisor
    lane owns the actual CreateMutex call; this is the shared derivation."""
    return ("Raphael_Supervisor" if is_main()
            else "Raphael_Supervisor_%s" % instance_name())
