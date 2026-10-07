#!/usr/bin/env python3
"""Raphael supervisor — Windows logon entry point, bring-up, health watchdog.

Owned by supervisor-dev (docs/ARCHITECTURE.md §2). Standard library only,
Python 3.10+ (Windows target); degrades to selfcheck/health-probe mode when run
on Linux so the WSL side can exercise it in CI.

Contract honored (docs/PROTOCOL.md):
  * Brain health  = HTTP GET http://127.0.0.1:<port>/health  (main port 8765)
  * Auth header   = X-Raphael-Token: <token>   (Authorization: Bearer also valid)
  * Token file    = %APPDATA%\\Raphael\\token   (WSL copy: ~/.raphael/token)
  * The token VALUE is never logged — only its path.

Instance isolation (docs/INTERFACES.md §d): every port/mutex/pidfile/lock/log
name derives from RAPHAEL_INSTANCE via supervisor/instance.py — unset = main
= historical defaults. Brain pidfile: ~/.raphael[/instance]/brain.pid (proper
per-user location), legacy /tmp/raphael-brain*.pid kept as fallback while
brain/app.py still writes it.

Profile awareness: under `cloud_temp` this supervisor never starts Ollama,
never pulls or warms local models — it still brings up Orb, Body, Brain and
the keep-alive/relay (Fish TTS is spawned by the Brain's voice layer, never
by the supervisor — INTERFACES §d forbids Fish spawns here).

Usage:
  python supervisor/main.py                # full run (Task Scheduler entry point)
  python supervisor/main.py --selfcheck    # environment self-test, exit 0/1
  python supervisor/main.py --once         # single health probe, then exit
  python supervisor/main.py --mutex-probe [--hold N]   # single-instance guard test

Log format: [YYYY-MM-DD HH:MM:SS] LEVEL message   -> logs/supervisor.log
Rotation: 5 MB cap, 3 backups (supervisor.log.1 .. .3).
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# supervisor/instance.py — RAPHAEL_INSTANCE derivation (INTERFACES §d),
# shared with the `raphael` CLI. Dual import: this file runs both as a
# plain script (Task Scheduler: pythonw supervisor/main.py -> module
# `instance` on sys.path) and as a package member (`import supervisor.main`).
try:
    from . import instance as inst_mod
except ImportError:                     # pragma: no cover - script mode
    import instance as inst_mod

# pythonw.exe host (scheduled task) has no console: sys.stdout/sys.stderr
# are None and print()/callback error reporting would crash. Route to devnull.
for _stream in ("stdout", "stderr"):
    if getattr(sys, _stream, None) is None:
        try:
            setattr(sys, _stream, open(os.devnull, "w", encoding="utf-8"))
        except OSError:
            pass

# --------------------------------------------------------------------------
# Contract constants (docs/PROTOCOL.md — port/header names are NOT negotiable)
# --------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"
LOG_DIR = REPO_ROOT / "logs"
LOG_PATH = LOG_DIR / "supervisor.log"
LOG_MAX_BYTES = 5 * 1024 * 1024       # 5 MB size cap
LOG_BACKUPS = 3                        # supervisor.log.1 / .2 / .3
MUTEX_NAME = "Raphael_Supervisor"      # single-instance mutex name (exact)
HEALTH_URL = "http://127.0.0.1:8765/health"
TOKEN_HEADER = "X-Raphael-Token"
ERROR_ALREADY_EXISTS = 183
IS_WINDOWS = os.name == "nt"

DEFAULT_CONFIG = {
    "paths": {
        # body_cmd / orb_dir / distro / brain_unit are the four keys the
        # supervisor contract requires from config.yaml; everything has a default.
        "body_cmd": "python body/win/main.py",
        "body_venv": "",            # optional override of the pinned Body venv
        "orb_dir": "body/orb",
        "distro": "Ubuntu-26.04",
        "wsl_user": "dami",
        "brain_unit": "raphael-brain",
        "ollama_unit": "ollama",
        "token_win": "",            # default: %APPDATA%\Raphael\token
        "wsl_sudo": False,          # true -> 'sudo -n systemctl ...' over wsl.exe
        "wsl_keepalive": True,      # hold a lightweight wsl.exe to keep the VM up
        "brain_relay": True,        # win 127.0.0.1:8765 -> wsl-ip:8765 splice
        "brain_mode": "auto",       # auto: systemd unit if installed, else process
        "brain_port": 8765,         # brain listen port (PROTOCOL fixed default)
    },
    "supervisor": {
        "health_url": HEALTH_URL,
        "health_interval": 5.0,     # health loop tick (spec: 5 s)
        "slow_interval": 15.0,      # PERMANENT_ERROR slow poll — 15 s, not 60:
                                    # Rule 15 SPEED: recovery detection must
                                    # stay near-instant even after a failure
                                    # streak (probes, not restarts, detect it)
        "probe_timeout": 3.0,
        "backoff_base": 5.0,        # 5s -> 10s -> 20s ...
        "backoff_cap": 60.0,        # ... cap 60 s (Rule 15: no multi-minute
                                    # restart limbo in normal operation;
                                    # was 300 s pre-Wave-3)
        "backoff_max_attempts": 10, # ... max 10 consecutive
        "bringup_timeout": 60.0,    # WSL bring-up poll budget (spec: 60 s)
        "bringup_poll": 5.0,
        "heartbeat_interval": 300.0,
    },
}

# Localhost only: never route the health probe through an HTTP proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# --------------------------------------------------------------------------
# Logging with size-cap rotation
# --------------------------------------------------------------------------
class Logger:
    """`[ts] LEVEL msg` lines -> logs/supervisor[_<instance>].log (5 MB, 3 backups)."""

    def __init__(self, path=None, max_bytes=LOG_MAX_BYTES,
                 backups=LOG_BACKUPS, echo=True):
        # Default log file derives from RAPHAEL_INSTANCE (main keeps
        # logs/supervisor.log byte for byte; lanes get logs/supervisor_<x>.log)
        # so parallel instances never fight over one rotating file.
        self.path = Path(path) if path is not None else inst_mod.log_path(
            "supervisor")
        self.max_bytes = int(max_bytes)
        self.backups = int(backups)
        self.echo = bool(echo)
        self._lock = threading.Lock()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # selfcheck still reports via stdout/stderr

    def _rotate(self):
        if not self.path.exists():
            return
        if self.path.stat().st_size < self.max_bytes:
            return
        oldest = Path("%s.%d" % (self.path, self.backups))
        try:
            if oldest.exists():
                oldest.unlink()
            for i in range(self.backups - 1, 0, -1):
                src = Path("%s.%d" % (self.path, i))
                if src.exists():
                    src.replace(Path("%s.%d" % (self.path, i + 1)))
            self.path.replace(Path("%s.1" % self.path))
        except OSError:
            pass

    def log(self, level, msg):
        line = "[%s] %s %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                               level, msg)
        with self._lock:
            try:
                self._rotate()
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:
                sys.stderr.write("supervisor: log write failed: %s\n" % exc)
        if self.echo:
            print(line, flush=True)
        return line

    def debug(self, msg):
        return self.log("DEBUG", msg)

    def info(self, msg):
        return self.log("INFO", msg)

    def warn(self, msg):
        return self.log("WARN", msg)

    def error(self, msg):
        return self.log("ERROR", msg)


# --------------------------------------------------------------------------
# Tiny YAML reader (flat + one level of nesting, comments, flow {} / [])
# --------------------------------------------------------------------------
def _split_flow(text):
    """Split a flow-style body on top-level commas only."""
    parts, depth, cur, quote = [], 0, "", None
    for ch in text:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            cur += ch
        elif ch in "[{":
            depth += 1
            cur += ch
        elif ch in "]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts]


def _scalar(token):
    tok = token.strip()
    if not tok:
        return None
    if tok[0] in "\"'":
        quote = tok[0]
        end = tok.find(quote, 1)
        return tok[1:end] if end != -1 else tok[1:]
    if tok.startswith("#"):
        return None
    if " #" in tok:
        tok = tok.split(" #", 1)[0].rstrip()
    if tok.startswith("[") and tok.endswith("]"):
        inner = tok[1:-1].strip()
        return [_scalar(p) for p in _split_flow(inner)] if inner else []
    if tok.startswith("{") and tok.endswith("}"):
        inner = tok[1:-1].strip()
        out = {}
        for part in _split_flow(inner):
            if ":" in part:
                key, _, val = part.partition(":")
                out[key.strip().strip("\"'")] = _scalar(val)
        return out
    low = tok.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~"):
        return None
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        pass
    return tok


def parse_config_text(text):
    """Minimal indentation-based YAML subset reader -> nested dict.

    Enough for config.yaml keys the supervisor reads (paths: / supervisor:).
    No pip dependency — stdlib only.
    """
    root = {}
    stack = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key = key.strip().strip("\"'")
        if not key:
            continue
        rest = rest.strip()
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if not rest or rest.startswith("#"):
            child = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(rest)
    return root


def _deep_copy(value):
    """Structural copy for config trees (dicts/lists copied, scalars kept)."""
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


def _deep_merge(base, over):
    # Deep-copy base first: `out = dict(base)` left NESTED defaults (e.g.
    # cfg["paths"]) SHARED with DEFAULT_CONFIG, so a single mutation
    # (instance port override, a test tweak) silently corrupted every later
    # load_config() in the same process. Found by supervisor instance tests.
    out = _deep_copy(base)
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = _deep_copy(val)
    return out


def _normalize(cfg, parsed):
    """Accept both layouts found in the wild:
      paths.distro / paths.brain_unit / ...        (supervisor contract)
      supervisor.distro / supervisor.brain_unit ... (config.yaml as written)
      supervisor.health_interval_s                 (*_s suffix naming)
      server.port                                  -> derive /health URL
    """
    paths = cfg.setdefault("paths", {})
    sup = cfg.setdefault("supervisor", {})
    alt = parsed.get("supervisor") if isinstance(parsed.get("supervisor"),
                                                 dict) else {}
    for key in ("distro", "wsl_user", "brain_unit", "ollama_unit",
                "body_cmd", "body_venv", "orb_dir", "token_win",
                "wsl_sudo", "wsl_keepalive"):
        if paths.get(key) in (None, "") and alt.get(key) not in (None, ""):
            paths[key] = alt[key]
    if "health_interval" not in alt and "health_interval_s" in alt:
        try:
            sup["health_interval"] = float(alt["health_interval_s"])
        except (TypeError, ValueError):
            pass
    # /health URL: PROTOCOL says Windows probes 127.0.0.1 even though the
    # server binds 0.0.0.0 — derive it only when no explicit health_url.
    parsed_sup = parsed.get("supervisor")
    parsed_sup = parsed_sup if isinstance(parsed_sup, dict) else {}
    parsed_srv = parsed.get("server")
    parsed_srv = parsed_srv if isinstance(parsed_srv, dict) else {}
    if "health_url" not in parsed_sup:
        port = parsed_srv.get("port") or 8765
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = 8765
        sup["health_url"] = "http://127.0.0.1:%d/health" % port
    return cfg


def _apply_instance(cfg, note):
    """INTERFACES §d: derive instance values into cfg (port + health URL).

    main + no RAPHAEL_PORT = today's exact behavior (config-derived values
    untouched). Any other instance — or an explicit RAPHAEL_PORT — overrides
    paths.brain_port and supervisor.health_url from the derivation table.
    """
    raw = str(os.environ.get("RAPHAEL_INSTANCE", "")).strip()
    inst = inst_mod.instance_name()
    cfg["instance"] = inst
    parts = [note]
    if raw and raw != inst:
        parts.append("RAPHAEL_INSTANCE sanitized to %s" % inst)
    env_port = os.environ.get("RAPHAEL_PORT")
    if inst != "main" or env_port:
        port = inst_mod.instance_port(
            inst, default=cfg["paths"].get("brain_port"))
        cfg["paths"]["brain_port"] = port
        cfg["supervisor"]["health_url"] = inst_mod.health_url(port)
        parts.append("instance=%s port=%d mutex=%s"
                     % (inst, port, inst_mod.mutex_name(inst)))
        if not inst_mod.known_instance(inst) and not env_port:
            # Fail closed (INTERFACES §d + qa "never guess a port" +
            # brain-core's config.port()): a silent fallback to 8765 would
            # collide with the LIVE main instance the moment a shadow/extra
            # instance appears without its row yet (Wave-5 shadow readiness).
            raise ValueError(
                "unknown RAPHAEL_INSTANCE %r and no RAPHAEL_PORT — refusing "
                "to guess a port (INTERFACES §d: set RAPHAEL_PORT explicitly "
                "or extend the §d table via the integrator; the old 8765 "
                "fallback would collide with the live main instance)" % inst)
    else:
        parts.append("instance=main port=%s" % cfg["paths"].get("brain_port"))
    return cfg, "; ".join(parts)


def load_config(path=CONFIG_PATH):
    """Return (cfg, note). Missing file -> defaults (never an error)."""
    path = Path(path)
    if not path.is_file():
        return _apply_instance(copy.deepcopy(DEFAULT_CONFIG),
                               "config.yaml not found at %s — using "
                               "built-in defaults" % path)
    text = path.read_text(encoding="utf-8", errors="replace")
    parsed = parse_config_text(text)
    cfg = _deep_merge(DEFAULT_CONFIG, parsed)
    _normalize(cfg, parsed)
    return _apply_instance(cfg, "config.yaml loaded from %s" % path)


def active_profile(cfg):
    """Active profile (INTERFACES §c): RAPHAEL_PROFILE wins -> config
    top-level `profile:` -> default cloud_temp."""
    env = os.environ.get("RAPHAEL_PROFILE")
    if env and env.strip():
        return env.strip()
    profile = cfg.get("profile")
    return str(profile) if profile else "cloud_temp"


# --------------------------------------------------------------------------
# Single-instance mutex (CreateMutexW, named "Raphael_Supervisor")
# --------------------------------------------------------------------------
def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def create_mutex(name=MUTEX_NAME):
    """Create/detect the single-instance mutex.

    Returns (handle, acquired). acquired=False means another supervisor
    instance already holds it (second launch must exit 0).
    """
    if not IS_WINDOWS:
        return None, True            # degraded: non-Windows runner
    k32 = _kernel32()
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                 ctypes.c_wchar_p]
    k32.CreateMutexW.restype = ctypes.c_void_p
    ctypes.set_last_error(0)
    handle = k32.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    duplicate = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    return handle, not duplicate


def release_mutex(handle):
    if handle and IS_WINDOWS:
        try:
            k32 = _kernel32()
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            k32.CloseHandle(handle)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _decode(data):
    """wsl.exe may emit UTF-8 or UTF-16LE depending on how it is invoked."""
    if not data:
        return ""
    if len(data) >= 2 and data.count(0) > len(data) // 4:
        even = data[: len(data) - (len(data) % 2)]
        try:
            return even.decode("utf-16-le", "replace")
        except Exception:
            pass
    return data.decode("utf-8", "replace")


def _one_line(text, limit=300):
    flat = " ".join(str(text).split())
    return flat[:limit] + ("..." if len(flat) > limit else "")


def _resolve(path_str):
    """Resolve a config path against the repo root (paths are repo-relative)."""
    expanded = os.path.expandvars(os.path.expanduser(str(path_str)))
    p = Path(expanded)
    if p.is_absolute() or str(p).startswith("\\\\"):
        return p
    return REPO_ROOT / p


def run_cmd(argv, timeout=30, env=None):
    """Run a command; never raises — returns (returncode, combined_text)."""
    merged = dict(os.environ)
    if env:
        merged.update(env)
    try:
        kwargs = {}
        if IS_WINDOWS:
            # CREATE_NO_WINDOW: the pythonw task host has no console for
            # children to inherit — Windows Terminal would otherwise open a
            # visible TAB for every wsl.exe probe.
            kwargs["creationflags"] = 0x08000000
        proc = subprocess.run(list(argv), capture_output=True,
                              timeout=timeout, env=merged, **kwargs)
    except subprocess.TimeoutExpired:
        return 124, "timeout after %ds: %s" % (timeout, argv[0])
    except FileNotFoundError:
        return 127, "command not found: %s" % argv[0]
    except OSError as exc:
        return 126, "%s: %s" % (type(exc).__name__, exc)
    out = _decode(proc.stdout)
    err = _decode(proc.stderr)
    text = out if not err else (out + ("\n" if out else "") + err)
    return proc.returncode, text.strip()


def find_wsl():
    for cand in ("wsl.exe", "wsl"):
        found = shutil.which(cand)
        if found:
            return found
    return None


def wsl_argv(cfg, *cmd, sudo=False):
    paths = cfg["paths"]
    argv = [find_wsl(), "-d", str(paths["distro"]),
            "-u", str(paths["wsl_user"]), "--"]
    # paths.wsl_sudo is a *systemctl* policy: applying it to every wsl
    # command would root-spawn the orb/keepalive too (electron as root =
    # broken display). Callers needing root pass sudo=True explicitly.
    if sudo:
        argv += ["sudo", "-n"]
    argv += [str(c) for c in cmd]
    return argv


def wsl_run(cfg, *cmd, timeout=30, sudo=False):
    if not find_wsl():
        return 127, "wsl.exe not found on PATH"
    return run_cmd(wsl_argv(cfg, *cmd, sudo=sudo), timeout=timeout,
                   env={"WSL_UTF8": "1"})


def wsl_state(cfg, unit, timeout=30):
    """`systemctl is-active <unit>` -> first line of output (needs no root)."""
    rc, out = wsl_run(cfg, "systemctl", "is-active", unit, timeout=timeout)
    if rc == 127:
        return "unknown"
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[0] if lines else ("unknown" if rc else "active")


def _needs_sudo(text):
    low = text.lower()
    return any(k in low for k in (
        "authentication", "access denied", "interactive authentication",
        "permission denied", "are you root", "must be root"))


def unit_load_state(cfg, unit, timeout=15):
    """`systemctl show -p LoadState <unit>` — unprivileged (no polkit).

    Polkit demands auth BEFORE reporting a missing unit, so this root-free
    query is the only way to tell "not installed yet" from "denied".
    """
    rc, out = wsl_run(cfg, "systemctl", "show", "-p", "LoadState", unit,
                      timeout=timeout)
    if rc != 0:
        return "unknown"
    for ln in out.splitlines():
        if ln.startswith("LoadState="):
            return ln.split("=", 1)[1].strip() or "unknown"
    return "unknown"


def systemctl_action(cfg, log, verb, unit, timeout=60):
    if unit_load_state(cfg, unit) == "not-found":
        log.info("unit '%s' not installed yet (Wave 2) — systemctl %s "
                 "deferred until the unit appears" % (unit, verb))
        return False
    rc, out = wsl_run(cfg, "systemctl", verb, unit, timeout=timeout,
                      sudo=bool(cfg["paths"].get("wsl_sudo")))
    if rc == 0:
        log.info("systemctl %s %s: OK" % (verb, unit))
        return True
    log.error("systemctl %s %s failed rc=%d: %s"
              % (verb, unit, rc, _one_line(out)))
    if _needs_sudo(out):
        log.error(
            "hint: root required for '%s %s' — set paths.wsl_sudo: true in "
            "config.yaml (uses 'sudo -n') or grant NOPASSWD systemctl to user "
            "'%s' (no password prompts allowed at runtime)"
            % (verb, unit, cfg["paths"]["wsl_user"]))
    return False


def _kill_brain_shell(cfg):
    """POSIX sh: cmdline-verified SIGTERM of the process-mode brain.

    Reads every path from instance.wsl_pidfiles() — the derived
    `<data-dir>/brain.pid` first (single source per INTERFACES §d =
    brain/config.py::pidfile()), plus the legacy /tmp path for `main`
    only (dual-write compat; lanes never touch /tmp). Never broad
    `pkill -f`: the target's /proc cmdline must actually be uvicorn
    brain.app before any kill. Exits 0 iff a kill was issued.
    """
    inst = cfg.get("instance") or inst_mod.instance_name()
    pidfiles = " ".join(inst_mod.wsl_pidfiles(inst))   # tilde-safe: sanitized
    port = int((cfg.get("paths") or {}).get("brain_port") or 8765)
    return (
        'killed=""; '
        'for f in %s; do '
        'p=$(cat "$f" 2>/dev/null); '
        'if [ -n "$p" ] && [ -r "/proc/$p/cmdline" ] && '
        'grep -qa "uvicorn brain.app" "/proc/$p/cmdline"; then '
        'kill "$p" 2>/dev/null; killed=1; break; fi; done; '
        # Bug G: pidfiles go stale (dead or recycled pids made the kill a
        # silent no-op) — resolve the REAL listener via ss -tlnp and verify
        # its cmdline before killing. Catches systemd/manual launches too
        # (absolute venv path, missed by the pgrep case below).
        'if [ -z "$killed" ]; then '
        'for p in $(ss -tlnp 2>/dev/null | grep ":%d " | grep -o "pid=[0-9]*" '
        '| cut -d= -f2 | sort -u); do '
        'if [ -r "/proc/$p/cmdline" ] && '
        'grep -qa "uvicorn brain.app" "/proc/$p/cmdline"; then '
        'kill "$p" 2>/dev/null; killed=1; fi; done; fi; '
        'if [ -z "$killed" ]; then '
        'for q in $(pgrep -f "uvicorn brain.app" 2>/dev/null); do '
        'head=$(tr "\\0" " " < /proc/$q/cmdline 2>/dev/null | cut -d" " -f1); '
        'case "$head" in brain/.venv/bin/python*|*/brain/.venv/bin/python*) '
        'kill "$q"; killed=1;; esac; '
        'done; fi; '
        'rm -f %s; [ -n "$killed" ]' % (pidfiles, port, pidfiles)
    )


def stop_brain(cfg, log):
    """Stop the brain (process mode: verified pidfile kill; systemd: stop).

    Runs the kill shell through wsl.exe when available (Windows supervisor
    / CLI), otherwise locally (the `raphael` CLI running inside WSL).
    Returns True iff a stop/kill was actually issued.
    """
    if brain_run_mode(cfg) == "process":
        shell = _kill_brain_shell(cfg)
        # Windows supervisor/CLI: reach the brain through wsl.exe. Inside
        # WSL (the raphael CLI's home turf) the brain is LOCAL — run the
        # kill shell directly, never via a nested wsl.exe round-trip.
        if IS_WINDOWS and find_wsl():
            rc, out = wsl_run(cfg, "sh", "-c", shell, timeout=10)
        else:
            rc, out = run_cmd(["sh", "-c", shell], timeout=10)
        killed = rc == 0
        if killed:
            log.info("brain process stopped (pidfile + cmdline verified)")
        elif out:
            log.info("brain process stop: nothing killable found (%s)"
                     % _one_line(out))
        else:
            log.info("brain process stop: nothing killable found "
                     "(pidfile empty or cmdline mismatch)")
        return killed
    unit = str(cfg["paths"]["brain_unit"])
    log.info("stopping brain via wsl.exe: %s"
             % " ".join(wsl_argv(cfg, "systemctl", "stop", unit,
                                 sudo=bool(cfg["paths"].get("wsl_sudo")))))
    return systemctl_action(cfg, log, "stop", unit)


def _wsl_cleanup_shell(cfg):
    """POSIX sh: full WSL-side teardown EXCEPT the brain (stop_brain owns
    that) + zero-survivor report (Bug G — `raphael stop` must leave ZERO
    processes on both sides).

    Kills: orb electron/node (identified by cwd = this repo's body/orb —
    never by bare 'electron', other worktrees' orbs survive), THIS
    instance's relay helper (scoped by its exact port argv), and the
    disposable keepalive sleep loops. Also removes the orb wrapper pidfile.
    Retries the brain-port check briefly so an in-flight SIGTERM settles.
    Exit 0 = clean; exit 1 + 'SURVIVORS:...' lines = leftovers.
    """
    inst = cfg.get("instance") or inst_mod.instance_name()
    port = int((cfg.get("paths") or {}).get("brain_port") or 8765)
    backend = inst_mod.relay_backend_port(port)
    repo = _wsl_path(REPO_ROOT) or str(REPO_ROOT)
    orb_frag = repo.rstrip("/") + "/body/orb"
    # $HOME spelling — a QUOTED tilde would never expand in sh
    orb_pf = inst_mod.wsl_data_dir(inst).replace("~", "$HOME", 1) + "/orb.pid"
    relay_sig = "wsl-relay.py %d %d" % (backend, port)
    kill_pass = (
        'for p in $(pgrep -f "electron|npm start" 2>/dev/null); do '
        'cwd=$(readlink /proc/$p/cwd 2>/dev/null); '
        'case "$cwd" in *%s*) kill "$p" 2>/dev/null;; esac; done; '
        'for p in $(pgrep -f "wsl-relay.py" 2>/dev/null); do '
        'cmd=$(tr "\\0" " " < /proc/$p/cmdline 2>/dev/null); '
        'case "$cmd" in *"%s"*) kill "$p" 2>/dev/null;; esac; done; '
        'for p in $(pgrep -f "while :; do sleep 3600" 2>/dev/null); do '
        'kill "$p" 2>/dev/null; done; '
        'rm -f "%s"; '
    ) % (orb_frag, relay_sig, orb_pf)
    surv_pass = (
        'for p in $(pgrep -f "electron|npm start" 2>/dev/null); do '
        'cwd=$(readlink /proc/$p/cwd 2>/dev/null); '
        'case "$cwd" in *%s*) surv="$surv orb:$p";; esac; done; '
        'for p in $(pgrep -f "wsl-relay.py" 2>/dev/null); do '
        'cmd=$(tr "\\0" " " < /proc/$p/cmdline 2>/dev/null); '
        'case "$cmd" in *"%s"*) surv="$surv relay:$p";; esac; done; '
        'for p in $(pgrep -f "while :; do sleep 3600" 2>/dev/null); do '
        'surv="$surv keepalive:$p"; done; '
    ) % (orb_frag, relay_sig)
    return (
        'surv=""; '
        '%s'
        'i=0; while ss -tlnp 2>/dev/null | grep -q ":%d " && [ "$i" -lt 8 ]; '
        'do sleep 0.5; i=$((i+1)); done; '
        'ss -tlnp 2>/dev/null | grep -q ":%d " && surv="$surv brainport:%d"; '
        '%s'
        'if [ -n "$surv" ]; then echo "SURVIVORS:$surv"; exit 1; fi; '
        'echo "wsl-side clean"; exit 0'
        % (kill_pass, port, port, port, surv_pass)
    )


def stop_wsl_side(cfg, log):
    """Teardown everything WSL-side except the brain; True = clean.

    Runs through wsl.exe from Windows, locally inside WSL. Called by
    `raphael stop` AFTER stop_brain (brain SIGTERM settles during the
    script's own port-wait loop)."""
    shell = _wsl_cleanup_shell(cfg)
    if IS_WINDOWS and find_wsl():
        rc, out = wsl_run(cfg, "sh", "-c", shell, timeout=25)
    else:
        rc, out = run_cmd(["sh", "-c", shell], timeout=25)
    for line in [ln for ln in out.splitlines() if ln.strip()]:
        if line.startswith("SURVIVORS"):
            log.error("wsl-side leftovers: %s" % line)
        else:
            log.info("wsl-side: %s" % line)
    clean = rc == 0 and "SURVIVORS" not in out
    if clean:
        log.info("wsl-side teardown clean (orb/relay/keepalive/brain port)")
    return clean


def _resolve_orb_pid(cfg):
    """The REAL orb pid inside WSL (Bug G): electron/node whose cwd is THIS
    repo's body/orb. None = no orb. One wsl round-trip — callers throttle."""
    repo = _wsl_path(REPO_ROOT) or str(REPO_ROOT)
    frag = repo.rstrip("/") + "/body/orb"
    shell = (
        'for p in $(pgrep -f "electron|npm start" 2>/dev/null); do '
        'cwd=$(readlink /proc/$p/cwd 2>/dev/null); '
        'case "$cwd" in *%s*) echo "$p"; break;; esac; done' % frag)
    if IS_WINDOWS and find_wsl():
        rc, out = wsl_run(cfg, "sh", "-c", shell, timeout=10)
    else:
        rc, out = run_cmd(["sh", "-c", shell], timeout=10)
    for tok in out.replace("\n", " ").split():
        if tok.isdigit():
            return int(tok)
    return None


class _ExternalOrb:
    """An orb we did NOT spawn is running (Bug G: integrator relaunched it
    manually). Adopted at bring-up so the supervisor never double-spawns
    (Electron's single-instance lock would kill the new copy anyway) and
    the heartbeat can show the truth."""

    def __init__(self, pid, cfg=None):
        self.pid = int(pid)
        self.cfg = cfg

    def poll(self):
        return None                          # adopted snapshot; heartbeat re-resolves


def _orb_heartbeat_txt(cfg, procs):
    """Truthful orb status for the heartbeat (Bug G): the REAL electron pid
    inside WSL, never the wsl.exe wrapper pid. Costs exactly one wsl
    round-trip PER HEARTBEAT (default 300 s) — never per health tick
    (Rule 14 RAM rule, Rule 15 speed: no extra load in normal operation)."""
    proc = procs.get("orb")
    real = _resolve_orb_pid(cfg)
    if isinstance(proc, _ExternalOrb):
        if real:
            return "pid=%d (adopted external)" % real
        return "exited (adopted pid=%d gone)" % proc.pid
    wrapper = proc.pid if proc is not None and proc.poll() is None else None
    if real:
        if wrapper and real != wrapper:
            return "pid=%d (wsl wrapper pid=%d)" % (real, wrapper)
        return "pid=%d" % real
    if wrapper:
        return "wrapper pid=%d (electron unresolved)" % wrapper
    if proc is None:
        return "not launched"
    return "exited (wrapper pid=%s rc=%s)" % (proc.pid, proc.poll())


def restart_brain(cfg, log, procs=None):
    if brain_run_mode(cfg) == "process":
        # Root-less recycle: verified stop, then respawn (see _kill_brain_shell).
        log.info("brain process mode: recycling via pidfile + respawn")
        stop_brain(cfg, log)
        time.sleep(1.5)
        if procs is not None:
            procs["brain"] = launch_brain(cfg, log)
        return True
    unit = str(cfg["paths"]["brain_unit"])
    log.info("restarting brain via wsl.exe: %s"
             % " ".join(wsl_argv(cfg, "systemctl", "restart", unit,
                                 sudo=bool(cfg["paths"].get("wsl_sudo")))))
    return systemctl_action(cfg, log, "restart", unit)


# --------------------------------------------------------------------------
# Token + health probe (PROTOCOL §2)
# --------------------------------------------------------------------------
def resolve_token(cfg):
    """Return (primary_path, token_or_None). Value is never logged."""
    paths = cfg["paths"]
    candidates = []
    # Instance-specific token candidates first (best-effort: until brain-core
    # derives tokens per instance, the shared main token below stays the
    # effective fallback — a missing instance file must not break probes).
    inst = cfg.get("instance") or inst_mod.instance_name()
    if inst != "main":
        appdata_i = os.environ.get("APPDATA")
        if appdata_i:
            candidates.append(Path(appdata_i) / "Raphael" / inst / "token")
        candidates.append(Path.home() / ".raphael" / inst / "token")
    if paths.get("token_win"):
        candidates.append(_resolve(paths["token_win"]))
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "Raphael" / "token")
    candidates.append(Path.home() / ".raphael" / "token")
    primary = candidates[0]
    for cand in candidates:
        try:
            if cand.is_file():
                value = cand.read_text(encoding="utf-8",
                                       errors="replace").strip()
                if value:
                    return cand, value
        except OSError:
            continue
    return primary, None


def probe_health(url, token, timeout=3.0):
    """GET /health -> ('ok'|'auth'|'down', detail). Token never in detail."""
    headers = {"User-Agent": "raphael-supervisor/1.0"}
    if token:
        headers[TOKEN_HEADER] = token
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
    except urllib.error.HTTPError as exc:
        code = exc.code
    except Exception as exc:      # connection refused / timeout / DNS
        return "down", "%s: %s" % (type(exc).__name__, exc)
    code = int(code)
    if 200 <= code < 300:
        return "ok", "HTTP %d" % code
    if code in (401, 403):
        return "auth", "HTTP %d" % code
    return "down", "HTTP %d" % code


# --------------------------------------------------------------------------
# Exponential backoff (5s -> 10s -> ... cap 300s, max 10 consecutive)
# --------------------------------------------------------------------------
class Backoff:
    def __init__(self, name, supervisor_cfg):
        self.name = name
        self.base = float(supervisor_cfg.get("backoff_base", 5.0))
        self.cap = float(supervisor_cfg.get("backoff_cap", 300.0))
        self.max_attempts = int(
            supervisor_cfg.get("backoff_max_attempts", 10))
        self.attempts = 0
        self.next_at = 0.0

    @property
    def exhausted(self):
        return self.attempts >= self.max_attempts

    def record_failure(self):
        self.attempts += 1
        delay = min(self.cap, self.base * (2 ** (self.attempts - 1)))
        self.next_at = time.monotonic() + delay
        return self.attempts, delay

    def reset(self):
        self.attempts = 0
        self.next_at = 0.0


# --------------------------------------------------------------------------
# Phase 1 — orb + body launch (orb FIRST, per architecture)
# --------------------------------------------------------------------------
def _child_env(env):
    """Merge a constructed child env OVER os.environ — never a replace.

    Approved pc-control request (2026-10-06): building an explicit env must
    never UNSET anything, least of all RAPHAEL_INSTANCE — os.environ's value
    survives unless the caller deliberately overrides it.
    """
    if not env:
        return None
    merged = dict(os.environ)
    merged.update(env)
    return merged


def instance_env(cfg, extra=None):
    """The instance triple every explicitly-constructed child env carries
    (approved pc-control request, 2026-10-06): RAPHAEL_INSTANCE,
    RAPHAEL_PORT, RAPHAEL_TOKEN_PATH — so a child derives the same instance
    context without re-deriving it. Token path is the supervisor-resolved
    primary (Windows-side for Windows children; WSL children get shell
    exports instead — see launch_brain/launch_orb)."""
    inst = cfg.get("instance") or inst_mod.instance_name()
    port = int(cfg["paths"].get("brain_port") or 8765)
    token_path, _token = resolve_token(cfg)
    env = {
        "RAPHAEL_INSTANCE": str(inst),
        "RAPHAEL_PORT": str(port),
        "RAPHAEL_TOKEN_PATH": str(token_path),
    }
    if extra:
        env.update(extra)
    return env


def _spawn(inner, cwd, log, label, log_file, env=None):
    """Spawn a detached child. `inner` is an argv list or a raw command string.

    UNC cwd (repo lives on \\wsl.localhost\\...) is handled via `pushd`, since
    cmd.exe refuses UNC working directories. `env` (optional) is MERGED over
    os.environ via _child_env — a wholesale replace is never done, so
    RAPHAEL_INSTANCE and friends survive into every child.
    """
    if isinstance(inner, str):
        inner_str = inner
        as_list = None
    else:
        as_list = list(inner)
        inner_str = (subprocess.list2cmdline(as_list) if IS_WINDOWS
                     else " ".join(shlex.quote(x) for x in as_list))
    child_env = _child_env(env)
    cwd_str = str(cwd)
    out = None
    try:
        out = open(log_file, "ab", buffering=0)
        if IS_WINDOWS:
            # CREATE_NO_WINDOW — NOT DETACHED_PROCESS: Win11's default
            # terminal (Windows Terminal) opens a VISIBLE TAB for every
            # console-less process (DETACHED made cmd/wsl.exe request a
            # console and WT hosted it -> the "4 mystery tabs"). Hidden
            # console instead: no window, no tab, no flash.
            flags = 0x08000000
            if as_list is not None:
                # argv children are self-contained (absolute script path, or
                # wsl-side `cd` inside the command): never cwd them through
                # pushd — its temp drive letter made wsl.exe print
                # "Failed to translate 'Z:\home\...'".
                target = as_list
                kwargs = {"shell": False,
                          "cwd": None if cwd_str.startswith("\\\\") else cwd_str}
            elif cwd_str.startswith("\\\\"):
                # string child + UNC cwd: pushd maps the UNC to a temp drive
                target = 'pushd "%s" && %s' % (cwd_str, inner_str)
                kwargs = {"shell": True, "cwd": None}
            else:
                target = ["cmd.exe", "/c", inner_str]
                kwargs = {"shell": False, "cwd": cwd_str}
            kwargs["creationflags"] = flags
        else:
            if as_list is not None:
                target, kwargs = as_list, {"shell": False, "cwd": cwd_str}
            else:
                target = ["sh", "-c", inner_str]
                kwargs = {"shell": False, "cwd": cwd_str}
        kwargs.update(stdout=out, stderr=subprocess.STDOUT,
                      stdin=subprocess.DEVNULL, env=child_env)
        proc = subprocess.Popen(target, **kwargs)
        log.info("%s launched pid=%d cmd=%s" % (label, proc.pid, inner_str))
        return proc
    except OSError as exc:
        log.error("%s launch failed (cmd=%s): %s" % (label, inner_str, exc))
        return None
    finally:
        if out is not None:
            out.close()


def _wsl_path(unc):
    """\\wsl.localhost\\<distro>\\home\\... (or \\wsl$\\...) -> /home/...

    Returns None when `unc` is not a WSL UNC path.
    """
    s = str(unc).replace("\\", "/")
    low = s.lower()
    for pfx in ("//wsl.localhost/", "//wsl$/"):
        if low.startswith(pfx):
            rest = s[len(pfx):]
            return "/" + rest.split("/", 1)[1] if "/" in rest else "/"
    return None


def launch_orb(cfg, log):
    """Phase 1a: Electron orb FIRST so the UI shows 'starting' immediately.

    The orb runs INSIDE WSL (start script = Linux-only `VAR=val electron`
    syntax + the WSLg window). Windows-side `npm start` used to die with no
    output, so the orb only ever appeared when a dev instance was up.

    Bug G (Wave 3): first resolve whether an orb is ALREADY running (e.g.
    relaunched manually during the live gate) and ADOPT it — a second copy
    would lose Electron's single-instance lock while the supervisor tracked
    a dead wrapper pid. The inner shell also writes
    `~/.raphael[/instance]/orb.pid` so teardown can verify the real thing.
    """
    existing = _resolve_orb_pid(cfg)
    if existing:
        log.info("orb: existing instance adopted (real pid=%d) — not "
                 "spawning a second copy (Bug G)" % existing)
        return _ExternalOrb(existing, cfg)
    orb_dir = _resolve(cfg["paths"].get("orb_dir") or "body/orb")
    if not (orb_dir / "package.json").is_file():
        log.warn("orb not ready — %s/package.json missing (owned by orb-dev); "
                 "continuing without orb" % orb_dir)
        return None
    start_script = False
    try:
        pkg = json.loads((orb_dir / "package.json").read_text(
            encoding="utf-8", errors="replace"))
        start_script = bool((pkg.get("scripts") or {}).get("start"))
    except (OSError, ValueError) as exc:
        log.warn("orb package.json unreadable (%s) — falling back to "
                 "npx electron ." % exc)
    wsl_cmd = "npm start" if start_script else "npx electron ."
    wsl_dir = _wsl_path(orb_dir)
    if wsl_dir is None:
        log.warn("orb_dir %s is not a WSL UNC path — cannot launch the orb "
                 "inside WSL; skipping" % orb_dir)
        return None
    # RAPHAEL_ORB_TOKEN: the orb refuses to connect without it (config.js
    # token=null -> silent offline ALL DAY in production). The $(cat ...) is
    # expanded INSIDE the inner shell — the token never appears in any argv.
    # Instance triple (approved pc-control request): RAPHAEL_INSTANCE +
    # RAPHAEL_PORT + RAPHAEL_TOKEN_PATH, the last picked by EXISTENCE
    # (instance token first, shared main token fallback — WSL-side paths).
    inst = cfg.get("instance") or inst_mod.instance_name()
    port = int(cfg["paths"].get("brain_port") or 8765)
    data_dir_home = inst_mod.wsl_data_dir(inst).replace("~", "$HOME", 1)
    inner = wsl_argv(cfg, "sh", "-lc",
                     "export RAPHAEL_INSTANCE=%s RAPHAEL_PORT=%d; "
                     "tp=%s/token; [ -f \"$tp\" ] || tp=$HOME/.raphael/token; "
                     "export RAPHAEL_TOKEN_PATH=\"$tp\"; "
                     "export RAPHAEL_ORB_TOKEN=$(cat \"$tp\" 2>/dev/null); "
                     "echo $$ > %s/orb.pid; "
                     "cd %s && exec %s"
                     % (shlex.quote(inst), port, data_dir_home,
                        data_dir_home, shlex.quote(wsl_dir), wsl_cmd))
    return _spawn(inner, orb_dir, log, "orb", inst_mod.log_path("orb"))


def _split_body_cmd(raw):
    parts = shlex.split(raw, posix=not IS_WINDOWS)
    if not IS_WINDOWS:
        return parts
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'"
            else p for p in parts]


def body_venv_python(cfg):
    """Pinned Body venv interpreter, or None (system Python fallback).

    System Python 3.10 is EOL around 2026-10 (Wave-2 task: the Body gets
    its own pinned venv/Python). Lookup order: config paths.body_venv ->
    %LOCALAPPDATA%\\Raphael\\body-venv (scripts/install-body-venv.ps1
    default) -> repo .venv-body (dev). Missing -> caller degrades to its
    own interpreter and selfcheck warns.
    """
    candidates = []
    configured = str(cfg["paths"].get("body_venv") or "").strip()
    if configured:
        candidates.append(_resolve(configured))
    localapp = os.environ.get("LOCALAPPDATA")
    if localapp:
        candidates.append(Path(localapp) / "Raphael" / "body-venv" /
                          "Scripts" / "python.exe")
    candidates.append(REPO_ROOT / ".venv-body" / "Scripts" / "python.exe")
    for cand in candidates:
        found = _venv_python_in(cand)
        if found:
            return found
    return None


def _venv_python_in(path):
    """Accept either the interpreter file itself or a venv directory."""
    try:
        if path.is_file():
            return path
        if path.is_dir():
            for sub in ("Scripts/python.exe", "bin/python", "bin/python3"):
                cand = path / sub
                if cand.is_file():
                    return cand
    except OSError:
        pass
    return None


def body_script(cfg):
    """Parse paths.body_cmd -> (exe, argv, script_path, why)."""
    raw = str(cfg["paths"].get("body_cmd") or "").strip()
    if not raw:
        return None, None, None, "paths.body_cmd not configured"
    try:
        parts = _split_body_cmd(raw)
    except ValueError as exc:
        return None, None, None, "paths.body_cmd unparsable: %s" % exc
    if not parts:
        return None, None, None, "paths.body_cmd empty"
    exe = parts[0]
    if exe.lower().replace(".exe", "") in ("python", "python3", "py"):
        # Pinned Body venv first; an EXPLICIT python path in body_cmd is
        # respected as-is (deliberate pin by whoever wrote the config).
        venv_py = body_venv_python(cfg)
        exe = str(venv_py) if venv_py else sys.executable
    script_tok = None
    for tok in parts[1:]:
        if "/" in tok or "\\" in tok or tok.endswith(".py"):
            script_tok = tok
            break
    if script_tok is None:
        if len(parts) < 2:
            return None, None, None, "paths.body_cmd has no script argument"
        script_tok = parts[1]
    script_path = _resolve(script_tok)
    argv = [exe] + [str(script_path) if t == script_tok else t
                    for t in parts[1:]]
    return exe, argv, script_path, ""


def brain_run_mode(cfg):
    """auto: systemd unit when installed, else 'process' (root-less bring-up).

    Installing raphael-brain.service needs root the orchestrator does not have
    (NOPASSWD grant is a user action, see docs/TODO.md §3b) — process mode
    makes Wave 2 fully autonomous meanwhile: supervisor spawns uvicorn itself.
    """
    pref = str(cfg["paths"].get("brain_mode", "auto")).lower()
    if pref == "process":
        return "process"
    if unit_load_state(cfg, str(cfg["paths"]["brain_unit"])) == "not-found":
        return "systemd" if pref == "systemd" else "process"
    return "systemd"


def launch_brain(cfg, log):
    """Process mode: run the brain directly under wsl (no root/systemd)."""
    repo_wsl = _wsl_path(REPO_ROOT)
    if not repo_wsl:
        log.warn("brain process mode: repo is not a WSL UNC path — cannot launch")
        return None
    port = int(cfg["paths"].get("brain_port") or 8765)
    inst = cfg.get("instance") or inst_mod.instance_name()
    pidfiles = inst_mod.wsl_pidfiles(inst)
    data_dir = inst_mod.wsl_data_dir(inst)
    # $$ survives exec -> pidfile names uvicorn exactly (recycle by pid +
    # cmdline check instead of broad `pkill -f`, which can match unrelated
    # processes whose argv merely contains the string — e.g. dev shells).
    # Pidfile = proper per-user location (~/.raphael[/instance]/brain.pid);
    # the legacy /tmp path is left alone for brain/app.py's own write.
    # RAPHAEL_INSTANCE/RAPHAEL_PORT are exported so brain-core derives the
    # same instance values (INTERFACES §c/§d) it would get under systemd;
    # RAPHAEL_PIDFILE lets brain/app.py write the SAME proper path ($HOME
    # expands here so Python receives an absolute path — see docs/requests/
    # infra__to__brain-core__pidfile-location.md).
    pidfile_env = pidfiles[0]
    if pidfile_env.startswith("~"):
        pidfile_env = "$HOME" + pidfile_env[1:]
    # RAPHAEL_TOKEN_PATH: point the Brain at a token file that EXISTS —
    # instance token first, shared main token as fallback (mirrors
    # resolve_token ordering; WSL-side paths only, never a Windows path).
    data_dir_home = data_dir.replace("~", "$HOME", 1)
    inner = wsl_argv(
        cfg, "sh", "-lc",
        "export RAPHAEL_INSTANCE=%s RAPHAEL_PORT=%d "
        "RAPHAEL_PIDFILE=\"%s\"; "
        "tp=%s/token; [ -f \"$tp\" ] || tp=$HOME/.raphael/token; "
        "export RAPHAEL_TOKEN_PATH=\"$tp\"; "
        "mkdir -p %s; echo $$ > %s; cd %s && exec "
        "brain/.venv/bin/python -m uvicorn brain.app:app "
        "--host 127.0.0.1 --port %d"
        % (shlex.quote(inst), port, pidfile_env, data_dir_home, data_dir,
           pidfiles[0], shlex.quote(repo_wsl), port))
    log.info("brain process: launching uvicorn (127.0.0.1:%d) instance=%s "
             "pidfile=%s" % (port, inst, pidfiles[0]))
    return _spawn(inner, REPO_ROOT, log, "brain",
                  inst_mod.log_path("brain"))


def launch_body(cfg, log):
    """Phase 1b / watchdog: relaunch the Windows Body from paths.body_cmd."""
    exe, argv, script_path, why = body_script(cfg)
    if argv is None:
        return None
    if not Path(script_path).is_file():
        log.warn("body not ready — %s missing (owned by body-dev); "
                 "will retry when it appears" % script_path)
        return None
    # Instance triple for the child (approved pc-control request): the Body
    # derives its single-instance lock from RAPHAEL_INSTANCE (INTERFACES §d:
    # %TMP%\\raphael_body[_<instance>].lock) and gets the same port/token
    # context the supervisor resolved. Merge never unsets anything.
    return _spawn(argv, REPO_ROOT, log, "body",
                  inst_mod.log_path("body"),
                  env=instance_env(cfg))


def _external_body_pid():
    """PID the body wrote into its single-instance lock (authoritative — the
    rc=0 bounce pid we used to store was always DEAD, so it could never be
    used for liveness). Lock name derives from RAPHAEL_INSTANCE (§d)."""
    try:
        txt = (Path(tempfile.gettempdir()) /
               inst_mod.body_lock_name()).read_text()
        return int(txt.strip())
    except (OSError, ValueError):
        return None


def _pid_exists(pid: int) -> bool:
    if os.name == 'nt':
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


class _ExternalBody:
    """Sentinel: a body instance we did not start is running (rc==0 exit).

    Liveness (TODO §3c fix, found when a crashed external body was never
    relaunched): poll() checks the PID the body recorded in its lock file —
    no lock / dead pid -> -1 ('dead') so body_status relaunches it.
    """

    def __init__(self, pid=None):
        self.pid = pid  # bounce pid (always dead) — kept only for call-compat

    def poll(self):
        pid = _external_body_pid()
        if pid is None:
            return -1  # no lock -> no body holding the single-instance slot
        try:
            return None if _pid_exists(pid) else -1
        except Exception:  # noqa: BLE001 — unknown -> assume running (old behavior)
            return None


def body_status(cfg, procs):
    """-> ('running'|'dead'|'unconfigured', detail)."""
    proc = procs.get("body")
    if proc is not None:
        rc = proc.poll()
        if rc is None:
            return "running", "pid=%s" % getattr(proc, "pid", "?")
        if isinstance(proc, _ExternalBody):
            if rc is None:
                return "running", ("external instance (lock-verified alive) "
                                   "— unsupervised")
            procs["body"] = None
            return "dead", "external body exited (lock pid gone) — relaunching"
        if rc == 0:
            procs["body"] = _ExternalBody(getattr(proc, "pid", -1))
            return "running", ("external instance (clean exit rc=0, likely "
                               "single-instance handoff) — unsupervised")
        procs["body"] = None
        return "dead", "pid=%s exited rc=%s" % (getattr(proc, "pid", "?"), rc)
    _exe, _argv, script_path, why = body_script(cfg)
    if script_path is None:
        return "unconfigured", why
    if not Path(script_path).is_file():
        return "unconfigured", "not ready — %s missing" % script_path
    return "dead", "script present but not running (%s)" % script_path


# --------------------------------------------------------------------------
# Phase 2 — WSL bring-up (systemd -> brain -> ollama) + keep-alive
# --------------------------------------------------------------------------
def start_keepalive(cfg, log):
    """Hold a lightweight `wsl.exe` so the VM is not idle-stopped."""
    if not cfg["paths"].get("wsl_keepalive", True):
        return None
    if not find_wsl():
        return None
    inner = wsl_argv(cfg, "sh", "-c", "while :; do sleep 3600; done")
    return _spawn(inner, REPO_ROOT, log, "wsl-keepalive",
                  inst_mod.log_path("wsl-keepalive"))


def _wsl_ip(cfg):
    """First IPv4 of the WSL distro (hostname -I), or None."""
    rc, out = wsl_run(cfg, "hostname", "-I", timeout=15)
    if rc != 0:
        return None
    for tok in out.replace(",", " ").split():
        if tok.count(".") == 3 and all(part.isdigit() for part in tok.split(".")):
            return tok
    return None


def _relay_listener(listen_port):
    """Windows-side relay socket — binds 127.0.0.1 ONLY.

    This bind is deliberately NOT configurable: the PROTOCOL localhost
    contract is the entire point of the relay (audited 2026-10-06 — no
    0.0.0.0/any-interface bind exists anywhere in the relay chain except
    the WSL helper leg, which MUST sit on the VM's NAT address because
    Windows dials it over the vNIC — packets from Windows never arrive on
    the VM's loopback. See scripts/NETWORK-SECURITY.md and
    scripts/win/allow-brain-localhost.ps1 for the loopback-only end state).
    Raises OSError if the port cannot be bound.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", listen_port))   # 127.0.0.1 ONLY — never 0.0.0.0
    srv.listen(64)
    return srv


def _wsl_networking_mode(cfg):
    """'nat' | 'mirrored' | None (wslinfo unavailable/failed)."""
    rc, out = wsl_run(cfg, "wslinfo", "--networking-mode", timeout=10)
    if rc != 0:
        return None
    return out.strip().lower() or None


def start_brain_relay(cfg, log, listen_port=None, backend_port=None):
    """User-space TCP splice: Windows 127.0.0.1:<port> -> <wsl-ip>:<helper>.

    Why this exists (verified 2026-10-05): Windows' built-in WSL localhost
    forwarding is blocked by the Hyper-V firewall on this machine
    (win->127.0.0.1:8765 = refused while win->172.x.x.x:8765 connects). The
    admin fix is a NARROW per-port Hyper-V rule (optional user-run script
    scripts/win/allow-brain-localhost.ps1) — NOT the blanket
    -DefaultInboundAction Allow. Until that rule (or mirrored networking)
    is in place, this relay keeps every Windows client on the PROTOCOL's
    localhost-only address with zero privileges.

    Legs (127.0.0.1 ONLY where the platform allows):
      Windows leg  : bind 127.0.0.1:<port>        — loopback, never wildcard
      WSL helper   : bind <vm NAT ip>:<helper>    — MUST be the NAT address:
                     Windows dials it over the vNIC; loopback binds are
                     unreachable from Windows while native forwarding is
                     firewalled. Exactly one address — never 0.0.0.0.
      Brain        : 127.0.0.1:<port>             — loopback (PROTOCOL §1)

    Skip policy: mirrored networking serves localhost natively -> no relay
    at all. Config: paths.brain_relay (leg), paths.brain_relay_helper
    (helper leg; false = narrow-rule mode, pair with brain_relay: false).
    """
    if not IS_WINDOWS or not cfg["paths"].get("brain_relay", True):
        return None
    if listen_port is None:
        listen_port = int(cfg["paths"].get("brain_port") or 8765)
    if backend_port is None:
        backend_port = inst_mod.relay_backend_port(listen_port)

    mode = _wsl_networking_mode(cfg)
    if mode and "mirrored" in mode:
        log.info("brain relay: WSL networking mode '%s' — native localhost "
                 "forwarding applies, relay skipped (127.0.0.1 end-to-end)"
                 % mode)
        return None

    state = {"ip": None, "warned_at": 0.0}

    def discover():
        ip = _wsl_ip(cfg)
        if ip:
            state["ip"] = ip
            log.info("brain relay: backend wsl %s:%d (helper leg)" % (ip, backend_port))
        return ip

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
        backend = None
        for _attempt in (0, 1):
            ip = state["ip"] or discover()
            if not ip:
                break
            try:
                backend = socket.create_connection((ip, backend_port), timeout=5)
                backend.settimeout(None)  # connect timeout must NOT stick (see
                # scripts/wsl-relay.py header comment — it killed WS streams
                # after ~5s of silence between server pings)
                break
            except OSError:
                state["ip"] = None  # distro restarted -> IP changed, rediscover
        if backend is None:
            try:
                client.close()
            except OSError:
                pass
            now = time.time()
            if now - state["warned_at"] > 60:
                state["warned_at"] = now
                log.warn("brain relay: backend wsl:%d unreachable (helper or "
                         "brain not up yet?) — client disconnected; retrying"
                         % backend_port)
            return
        threading.Thread(target=pipe, args=(client, backend),
                         daemon=True).start()
        pipe(backend, client)
        for sock in (client, backend):
            try:
                sock.close()
            except OSError:
                pass

    slots = threading.BoundedSemaphore(64)  # security: bounded splice threads

    def accept_loop():
        try:
            srv = _relay_listener(listen_port)   # 127.0.0.1 ONLY (raises OSError)
        except OSError as exc:
            log.warn("brain relay: cannot bind 127.0.0.1:%d (%s) — relay off"
                     % (listen_port, exc))
            return
        log.info("brain relay: listening 127.0.0.1:%d -> wsl:%d (localhost "
                 "contract preserved)" % (listen_port, backend_port))
        while True:
            try:
                client, _addr = srv.accept()
            except OSError:
                return
            if not slots.acquire(blocking=False):
                try:
                    client.close()
                except OSError:
                    pass
                continue  # security: cap reached, shed load
            def _serve(c=client):
                try:
                    handle(c)
                finally:
                    slots.release()
            threading.Thread(target=_serve, daemon=True).start()

    # WSL helper leg: binds EXACTLY ONE address inside the VM — the NAT IP
    # (never 0.0.0.0; a loopback bind would be unreachable from Windows),
    # then dials the Brain's loopback. Detached+hidden; outlives supervisor
    # restarts (a duplicate spawn just exits on bind-conflict, logged to
    # wsl-relay.log). Gated by paths.brain_relay_helper: false for the
    # narrow-firewall-rule end state where the relay is disabled entirely.
    if not cfg["paths"].get("brain_relay_helper", True):
        log.warn("brain relay: paths.brain_relay_helper=false but the "
                 "Windows leg needs the helper backend (wsl:%d) — set "
                 "paths.brain_relay: false too unless native localhost "
                 "forwarding is verified (scripts/win/allow-brain-"
                 "localhost.ps1)" % backend_port)
    else:
        helper_unc = REPO_ROOT / "scripts" / "wsl-relay.py"
        helper_wsl = _wsl_path(helper_unc)
        if helper_wsl:
            _spawn(wsl_argv(cfg, "python3", helper_wsl, str(backend_port),
                            str(listen_port)),
                   helper_unc, log, "wsl-relay",
                   inst_mod.log_path("wsl-relay"))
        else:
            log.warn("brain relay: cannot derive wsl path for scripts/wsl-relay.py")

    threading.Thread(target=accept_loop, daemon=True).start()
    return "relay"


def bring_up_wsl(cfg, log, procs=None):
    S = cfg["supervisor"]
    paths = cfg["paths"]
    unit = str(paths["brain_unit"])
    ollama_unit = str(paths.get("ollama_unit") or "ollama")
    profile = active_profile(cfg)
    if not find_wsl():
        log.error("wsl.exe not found on PATH — WSL bring-up skipped; brain "
                  "health checks will fail until WSL is available")
        return False
    log.info("phase 2: WSL bring-up distro=%s user=%s profile=%s "
             "brain_unit=%s ollama_unit=%s"
             % (paths["distro"], paths["wsl_user"], profile, unit,
                ollama_unit))
    timeout = float(S.get("bringup_timeout", 60.0))
    poll = float(S.get("bringup_poll", 5.0))
    deadline = time.monotonic() + timeout
    state = "unknown"
    boot = True
    if brain_run_mode(cfg) == "process":
        # Root-less Wave-2 path: the systemd unit is not installed yet, so
        # skip60s of unit polling entirely and spawn the brain directly.
        log.info("brain process mode — unit '%s' not installed; spawning "
                 "brain directly under wsl (systemctl skipped)" % unit)
        state = "process"
        if procs is not None:
            procs["brain"] = launch_brain(cfg, log)
    else:
        while True:
            state = wsl_state(cfg, unit, timeout=60 if boot else 30)
            boot = False
            if state == "active":
                log.info("brain unit '%s' is active" % unit)
                break
            left = deadline - time.monotonic()
            if left <= 0:
                break
            log.info("brain unit '%s' state=%s — polling (%.0fs left)"
                     % (unit, state, left))
            time.sleep(min(poll, left))
        if state != "active":
            log.warn("brain unit '%s' still %s after %.0fs — issuing "
                     "'systemctl start'" % (unit, state, timeout))
            systemctl_action(cfg, log, "start", unit)
            verify_until = time.monotonic() + 30.0
            while time.monotonic() < verify_until:
                state = wsl_state(cfg, unit, timeout=30)
                if state == "active":
                    log.info("brain unit '%s' started OK" % unit)
                    break
                time.sleep(poll)
    # ---- Ollama: ONLY for profile `local` (cloud_temp contract, WAVES.md) --
    # Under cloud_temp the supervisor must never start Ollama, pull models,
    # or warm local models — no systemctl call, no state probe at all.
    # Fish TTS stays local in BOTH profiles but is spawned by the Brain's
    # voice layer (brain/app.py warmup), never by the supervisor.
    if profile == "local":
        ostate = wsl_state(cfg, ollama_unit, timeout=30)
        if ostate == "active":
            log.info("ollama unit '%s' is active" % ollama_unit)
        else:
            log.warn("ollama unit '%s' state=%s — issuing 'systemctl start'"
                     % (ollama_unit, ostate))
            systemctl_action(cfg, log, "start", ollama_unit, timeout=60)
            ostate = wsl_state(cfg, ollama_unit, timeout=30)
            log.info("ollama unit '%s' now %s" % (ollama_unit, ostate))
    else:
        log.info("profile %s: Ollama skipped — no local models started, no "
                 "model pulls, no warm (cloud chain: groq -> zen_free); "
                 "Orb/Body/Brain unaffected, Fish TTS started by the Brain"
                 % profile)
    if state not in ("active", "process"):
        log.error("brain unit '%s' NOT active (%s) — health watchdog will "
                  "keep retrying" % (unit, state))
    return state in ("active", "process")


# --------------------------------------------------------------------------
# Event hooks — WM_POWERBROADCAST (resume) + NotifyAddrChange (network)
# --------------------------------------------------------------------------
class EventHooks:
    def __init__(self):
        self.resume = threading.Event()     # resume-from-sleep
        self.network = threading.Event()    # IPv4/IPv6 address change
        self.stop_event = threading.Event()
        self.available = IS_WINDOWS
        self._threads = []
        self._wndproc = None                # keep callback alive
        self._power_tid = None

    def start(self, log):
        if not self.available:
            log.info("event hooks skipped (non-Windows runner) — "
                     "WM_POWERBROADCAST/NotifyAddrChange start on Windows")
            return
        for target, name in ((_power_thread, "power"),
                             (_addr_thread, "network")):
            thread = threading.Thread(target=target, args=(self, log),
                                      name="hook-" + name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self):
        self.stop_event.set()
        if self._power_tid and IS_WINDOWS:
            try:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostThreadMessageW(self._power_tid, 0x0012, 0, 0)
            except Exception:
                pass


def _power_thread(hooks, log):
    """Hidden top-level window that receives WM_POWERBROADCAST messages."""
    try:
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Pointer-sized Win32 args: WITHOUT argtypes ctypes falls back to
        # 32-bit c_int, so every pointer-valued wParam/lParam raised
        # "OverflowError: int too long to convert" inside wndproc (seen
        # repeatedly in the live smoke).
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        k32.GetModuleHandleW.restype = wintypes.HMODULE
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
            wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE,
            ctypes.c_void_p]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR,
                                            wintypes.HINSTANCE]
        WM_POWERBROADCAST = 0x0218
        PBT_APMSUSPEND = 0x0004
        PBT_APMRESUMECRITICAL = 0x0006
        PBT_APMRESUMESUSPEND = 0x0007
        PBT_APMRESUMEAUTOMATIC = 0x0012
        PBT_POWERSETTINGCHANGE = 0x0018
        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
            wintypes.WPARAM, wintypes.LPARAM)

        # ctypes.wintypes has no HCURSOR on Python 3.10 (power-hook crash found
        # by the live logon smoke) — HCURSOR is a plain handle (void pointer).
        if not hasattr(wintypes, "HCURSOR"):
            wintypes.HCURSOR = ctypes.c_void_p

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HCURSOR),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]

        class MSG(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                        ("wParam", wintypes.WPARAM),
                        ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD),
                        ("pt", wintypes.POINT)]

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_POWERBROADCAST:
                if wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND,
                              PBT_APMRESUMECRITICAL):
                    hooks.resume.set()
                    log.info("WM_POWERBROADCAST resume (wparam=0x%02X) — "
                             "immediate re-verify scheduled" % wparam)
                elif wparam == PBT_APMSUSPEND:
                    log.info("WM_POWERBROADCAST suspend (PBT_APMSUSPEND) — "
                             "entering sleep")
                elif wparam == PBT_POWERSETTINGCHANGE:
                    log.debug("WM_POWERBROADCAST power-setting change")
                return 1  # TRUE: message handled
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        hooks._wndproc = WNDPROC(wndproc)  # must outlive the message loop
        hinst = k32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = hooks._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = "RaphaelSupervisorPowerHook"
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            err = ctypes.get_last_error()
            if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                log.warn("RegisterClassW failed err=%d — power hook "
                         "unavailable" % err)
                return
        hwnd = user32.CreateWindowExW(
            0, "RaphaelSupervisorPowerHook", "Raphael Supervisor", 0,
            0, 0, 0, 0, None, None, hinst, None)
        if not hwnd:
            log.warn("CreateWindowExW failed err=%d — power hook unavailable"
                     % ctypes.get_last_error())
            return
        hooks._power_tid = k32.GetCurrentThreadId()
        log.info("power-event hook registered (hidden window, "
                 "WM_POWERBROADCAST=0x0218)")
        msg = MSG()
        while not hooks.stop_event.is_set():
            res = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if res <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.DestroyWindow(hwnd)
        user32.UnregisterClassW("RaphaelSupervisorPowerHook", hinst)
        log.info("power-event hook stopped")
    except Exception as exc:      # hooks are best effort, never fatal
        log.error("power-event hook crashed: %s: %s"
                  % (type(exc).__name__, exc))


def _addr_thread(hooks, log):
    """Re-armed NotifyAddrChange wait -> fires on IPv4/IPv6 address change."""
    try:
        from ctypes import wintypes
        iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        # OVERLAPPED layout: Internal, InternalHigh, union{Offset/OffsetHigh,
        # hEvent} — stable across x64.
        class _OS(ctypes.Structure):
            _fields_ = [("Offset", wintypes.DWORD),
                        ("OffsetHigh", wintypes.DWORD)]

        class _Union(ctypes.Union):
            _fields_ = [("os", _OS), ("hEvent", wintypes.HANDLE)]

        class OVERLAPPED_REAL(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_size_t),
                        ("InternalHigh", ctypes.c_size_t),
                        ("u", _Union)]

        iphlpapi.NotifyAddrChange.argtypes = [
            ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(OVERLAPPED_REAL)]
        iphlpapi.NotifyAddrChange.restype = wintypes.DWORD
        k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                     wintypes.BOOL, wintypes.LPCWSTR]
        k32.CreateEventW.restype = wintypes.HANDLE
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        ERROR_IO_PENDING = 997
        WAIT_OBJECT_0 = 0
        WAIT_FAILED = 0xFFFFFFFF
        announced = False
        while not hooks.stop_event.is_set():
            ev = k32.CreateEventW(None, True, False, None)
            if not ev:
                log.warn("CreateEventW failed — network-change hook "
                         "unavailable")
                return
            handle_out = wintypes.HANDLE()
            ov = OVERLAPPED_REAL()
            ov.u.hEvent = ev
            ctypes.set_last_error(0)
            rc = iphlpapi.NotifyAddrChange(ctypes.byref(handle_out),
                                           ctypes.byref(ov))
            err = ctypes.get_last_error()
            if rc not in (0, ERROR_IO_PENDING):
                log.warn("NotifyAddrChange failed rc=%d err=%d — "
                         "network-change hook unavailable" % (rc, err))
                k32.CloseHandle(ev)
                return
            if not announced:
                log.info("network-change hook registered (NotifyAddrChange)")
                announced = True
            while not hooks.stop_event.is_set():
                wait = k32.WaitForSingleObject(ev, 2000)
                if wait == WAIT_OBJECT_0:
                    hooks.network.set()
                    log.info("network address change detected — immediate "
                             "re-verify scheduled")
                    break
                if wait == WAIT_FAILED:
                    log.warn("WaitForSingleObject failed err=%d"
                             % ctypes.get_last_error())
                    break
            k32.CloseHandle(ev)
            if handle_out:
                k32.CloseHandle(handle_out)
    except Exception as exc:
        log.error("network-change hook crashed: %s: %s"
                  % (type(exc).__name__, exc))


# --------------------------------------------------------------------------
# Phase 3 — health loop, backoff restarts, resume/network handling
# --------------------------------------------------------------------------
def run_health_loop(cfg, log, hooks, procs):
    S = cfg["supervisor"]
    url = str(S.get("health_url", HEALTH_URL))
    timeout = float(S.get("probe_timeout", 3.0))
    interval = float(S.get("health_interval", 5.0))
    slow = float(S.get("slow_interval", 60.0))
    heartbeat_iv = float(S.get("heartbeat_interval", 300.0))
    brain_bo = Backoff("brain", S)
    body_bo = Backoff("body", S)
    perm_brain = False
    perm_body = False
    last_brain = None
    last_body = None
    next_tick = 0.0
    heartbeat_at = time.monotonic() + heartbeat_iv
    log.info("phase 3: health loop — interval %.0fs, slow %.0fs, backoff "
             "%.0fs..%.0fs x%d, probe %s"
             % (interval, slow, brain_bo.base, brain_bo.cap,
                brain_bo.max_attempts, url))

    def tick(now):
        nonlocal perm_brain, perm_body, last_brain, last_body, heartbeat_at
        token_path, token = resolve_token(cfg)
        state, detail = probe_health(url, token, timeout)

        # ---- brain ------------------------------------------------------
        if state == "ok":
            if brain_bo.attempts:
                log.info("brain healthy again after %d restart attempt(s)"
                         % brain_bo.attempts)
            brain_bo.reset()
            if perm_brain:
                perm_brain = False
                log.info("PERMANENT_ERROR cleared — brain healthy on slow "
                         "poll; resuming %.0fs interval" % interval)
            if last_brain != "ok":
                log.info("brain healthy (%s)" % detail)
            last_brain = "ok"
        elif state == "auth":
            # Reachable but token rejected: a restart cannot fix auth.
            brain_bo.reset()
            if perm_brain:
                perm_brain = False
                log.info("PERMANENT_ERROR cleared — brain reachable")
            if last_brain != "auth":
                log.warn("brain reachable but token rejected (%s) at %s — "
                         "token VALUE not logged; restart NOT issued "
                         "(auth cannot be fixed by restarting)"
                         % (detail, token_path))
            last_brain = "auth"
        else:
            if last_brain != "down":
                log.error("brain health check failed (%s) probe=%s"
                          % (detail, url))
            last_brain = "down"
            if perm_brain:
                log.info("brain still down (%s) — PERMANENT_ERROR slow poll"
                         % detail)
            elif brain_bo.attempts == 0 or now >= brain_bo.next_at:
                restart_brain(cfg, log, procs)
                attempts, delay = brain_bo.record_failure()
                log.warn("brain restart attempt %d/%d issued; next "
                         "probe+restart in %.0fs"
                         % (attempts, brain_bo.max_attempts, delay))
                if brain_bo.exhausted:
                    perm_brain = True
                    log.error("PERMANENT_ERROR brain: %d consecutive restart "
                              "attempts exhausted (base %.0fs cap %.0fs) — "
                              "retries STOPPED; slow-poll every %.0fs; "
                              "auto-resumes when health returns"
                              % (attempts, brain_bo.base, brain_bo.cap, slow))

        # ---- body -------------------------------------------------------
        bstate, bdetail = body_status(cfg, procs)
        if bstate == "running":
            if body_bo.attempts:
                log.info("body healthy again after %d restart attempt(s)"
                         % body_bo.attempts)
            body_bo.reset()
            if perm_body:
                perm_body = False
                log.info("PERMANENT_ERROR cleared — body running")
            if last_body != "running":
                log.info("body process alive (%s)" % bdetail)
            last_body = "running"
        elif bstate == "unconfigured":
            if last_body != "unconfigured":
                log.warn("body not ready — %s" % bdetail)
            last_body = "unconfigured"
        else:  # dead
            if last_body != "dead":
                log.error("body process dead (%s)" % bdetail)
            last_body = "dead"
            if perm_body:
                log.info("body still down — PERMANENT_ERROR slow poll (%s)"
                         % bdetail)
            elif body_bo.attempts == 0 or now >= body_bo.next_at:
                new_proc = launch_body(cfg, log)
                if new_proc is not None:
                    procs["body"] = new_proc
                attempts, delay = body_bo.record_failure()
                log.warn("body relaunch attempt %d/%d issued; next check in "
                         "%.0fs" % (attempts, body_bo.max_attempts, delay))
                if body_bo.exhausted:
                    perm_body = True
                    log.error("PERMANENT_ERROR body: %d consecutive relaunch "
                              "attempts exhausted — retries STOPPED; "
                              "slow-poll every %.0fs; auto-resumes when the "
                              "body comes back" % (attempts, slow))

        # ---- heartbeat (only when healthy; never token, never secrets) ---
        if (not perm_brain and not perm_body and state != "down"
                and bstate == "running" and now >= heartbeat_at):
            # Bug G: resolve the REAL orb pid here (one wsl round-trip per
            # heartbeat), not the wsl.exe wrapper — never every tick.
            log.info("healthy heartbeat — brain=%s body=running orb=%s"
                     % (state, _orb_heartbeat_txt(cfg, procs)))
            heartbeat_at = now + heartbeat_iv

    while not hooks.stop_event.is_set():
        if hooks.resume.is_set():
            hooks.resume.clear()
            log.info("resume-from-sleep — immediate re-verify pass "
                     "(backoff counters reset, PERMANENT_ERROR lifted)")
            brain_bo.reset()
            body_bo.reset()
            if perm_brain:
                perm_brain = False
                log.info("PERMANENT_ERROR (brain) lifted by resume — fresh "
                         "restart cycle allowed")
            if perm_body:
                perm_body = False
                log.info("PERMANENT_ERROR (body) lifted by resume — fresh "
                         "restart cycle allowed")
            now = time.monotonic()
            tick(now)
            next_tick = time.monotonic() + (
                slow if (perm_brain or perm_body) else interval)
        elif hooks.network.is_set():
            hooks.network.clear()
            log.info("network change — immediate re-verify pass "
                     "(Brain<->Body link re-check)")
            now = time.monotonic()
            tick(now)
            next_tick = time.monotonic() + (
                slow if (perm_brain or perm_body) else interval)
        now = time.monotonic()
        if now >= next_tick:
            tick(now)
            next_tick = now + (slow if (perm_brain or perm_body) else interval)
        time.sleep(0.5)


# --------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------
def _rotation_selftest():
    """Write >cap bytes through a small Logger and verify .1/.2/.3 exist."""
    tmp = LOG_DIR / "_selfcheck_rotate.log"
    stale = [tmp] + [Path("%s.%d" % (tmp, i)) for i in (1, 2, 3, 4)]
    for path in stale:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            return False, "cannot clean %s" % path
    logger = Logger(tmp, max_bytes=800, backups=3, echo=False)
    for i in range(80):
        logger.log("INFO", "rotation probe line %03d — padding padding" % i)
    backups = [Path("%s.%d" % (tmp, i)) for i in (1, 2, 3)]
    existing = [b for b in backups if b.exists()]
    overflow = Path("%s.4" % tmp).exists()
    ok = bool(existing) and not overflow
    detail = ("rotation verified: %d backup file(s) present (%s), "
              "4th-generation file absent"
              % (len(existing), ", ".join(b.name for b in existing)))
    for path in stale:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
    if not ok:
        detail = "rotation FAILED (%s)" % detail
    return ok, detail


def selfcheck(args):
    """Environment self-test. Health-down is EXPECTED and not a failure."""
    results = []  # (name, status, detail)

    log = Logger()
    log.info("selfcheck requested (repo=%s)" % REPO_ROOT)

    # 1 — single-instance mutex (name derives from RAPHAEL_INSTANCE, §d)
    if IS_WINDOWS:
        try:
            h1, acquired = create_mutex(inst_mod.mutex_name())
            if acquired:
                h2, duplicate = create_mutex(inst_mod.mutex_name())  # same-process second Create
                ok = not duplicate
                release_mutex(h2)
                release_mutex(h1)
                results.append(("single-instance mutex",
                                "PASS" if ok else "FAIL",
                                "CreateMutexW('%s') acquired; duplicate "
                                "detection %s"
                                % (inst_mod.mutex_name(),
                                   "OK" if ok else "BROKEN")))
            else:
                release_mutex(h1)
                results.append(("single-instance mutex", "PASS",
                                "held by another live instance — guard "
                                "works (second launch exits 0)"))
        except Exception as exc:
            results.append(("single-instance mutex", "FAIL", str(exc)))
    else:
        results.append(("single-instance mutex", "SKIP",
                        "non-Windows runner — exercised at Windows runtime "
                        "(CreateMutexW)"))

    # 2 — config parse
    try:
        cfg, note = load_config(args.config)
        paths = cfg["paths"]
        results.append(("config parse", "PASS",
                        "%s | distro=%s user=%s brain_unit=%s orb_dir=%s "
                        "body_cmd=%s"
                        % (note, paths["distro"], paths["wsl_user"],
                           paths["brain_unit"], paths["orb_dir"],
                           paths["body_cmd"])))
    except Exception as exc:
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        results.append(("config parse", "FAIL",
                        "%s: %s" % (type(exc).__name__, exc)))

    # 2b — instance isolation (INTERFACES §d): port/mutex/lock/pidfile all
    # derive from RAPHAEL_INSTANCE; main keeps the historical defaults.
    inst = inst_mod.instance_name()
    inst_port = inst_mod.instance_port(
        inst, default=cfg["paths"].get("brain_port"))
    inst_detail = ("instance=%s port=%d mutex=%s lock=%s pidfile=%s "
                   "log=%s"
                   % (inst, inst_port, inst_mod.mutex_name(inst),
                      inst_mod.body_lock_name(inst),
                      inst_mod.wsl_pidfiles(inst)[0],
                      inst_mod.log_path("supervisor", inst).name))
    if inst_mod.known_instance(inst) or os.environ.get("RAPHAEL_PORT"):
        results.append(("instance isolation", "PASS", inst_detail))
    else:
        results.append(("instance isolation", "WARN",
                        inst_detail + " | unknown instance — config port "
                        "kept, set RAPHAEL_PORT for real isolation"))

    # 2c — profile awareness: cloud_temp must skip Ollama/local models.
    profile = active_profile(cfg)
    if profile == "local":
        results.append(("profile", "PASS",
                        "%s — Ollama/local models ON (Wave 6 cutover)" % profile))
    else:
        results.append(("profile", "PASS",
                        "%s — Ollama/model pulls/model warm SKIPPED; "
                        "Orb/Body/Brain/Fish still started" % profile))

    # 2d — pinned Body venv (system Python 3.10 EOL ~2026-10)
    body_venv = body_venv_python(cfg)
    if body_venv:
        results.append(("body venv", "PASS",
                        "pinned interpreter: %s" % body_venv))
    else:
        results.append(("body venv", "WARN",
                        "pinned venv not found — body_cmd 'python' falls "
                        "back to this interpreter (this host: %s); on "
                        "Windows that is system Python 3.10, EOL ~2026-10 "
                        "— run scripts/install-body-venv.ps1"
                        % sys.version.split()[0]))

    # 3 — wsl.exe discovery
    wsl = find_wsl()
    status = "PASS" if wsl else ("FAIL" if IS_WINDOWS else "WARN")
    results.append(("wsl.exe discovery", status, wsl or "not found on PATH"))

    # 4 — /health probe (brain down is graceful, not a failure)
    token_path, token = resolve_token(cfg)
    url = str(cfg["supervisor"].get("health_url", HEALTH_URL))
    state, detail = probe_health(url, token,
                                 float(cfg["supervisor"]["probe_timeout"]))
    if state == "ok":
        results.append(("health probe %s" % url, "PASS", detail))
    elif state == "auth":
        results.append(("health probe %s" % url, "WARN",
                        "reachable but auth rejected (%s) token=%s"
                        % (detail, token_path)))
    else:
        results.append(("health probe %s" % url, "WARN",
                        "brain down (graceful, expected if Brain not "
                        "started yet): %s" % detail))

    # 5 — token file (path only)
    if token:
        results.append(("token file", "PASS",
                        "%s (%d chars, value not shown)"
                        % (token_path, len(token))))
    else:
        results.append(("token file", "WARN",
                        "missing at %s — run scripts/token-gen.sh"
                        % token_path))

    # 6 — log write + rotation
    try:
        Logger().info("selfcheck: logger write OK")
        rot_ok, rot_detail = _rotation_selftest()
        results.append(("log write + rotation",
                        "PASS" if rot_ok else "FAIL", rot_detail))
    except Exception as exc:
        results.append(("log write + rotation", "FAIL",
                        "%s: %s" % (type(exc).__name__, exc)))

    # 7 — event hooks availability
    if IS_WINDOWS:
        results.append(("event hooks", "PASS",
                        "WM_POWERBROADCAST window + NotifyAddrChange threads "
                        "will start at runtime"))
    else:
        results.append(("event hooks", "SKIP",
                        "non-Windows runner (hooks start on Windows)"))

    # ---- report --------------------------------------------------------
    print("Raphael supervisor selfcheck — repo=%s" % REPO_ROOT)
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
    for name, status, detail in results:
        counts[status] = counts.get(status, 0) + 1
        print("  [%-4s] %-24s %s" % (status, name, detail))
    print("SELFcheck RESULT: PASS=%d WARN=%d FAIL=%d SKIP=%d"
          % (counts["PASS"], counts["WARN"], counts["FAIL"],
             counts["SKIP"]))
    if counts["FAIL"]:
        log.error("selfcheck finished with FAIL=%d" % counts["FAIL"])
        print("SELFcheck FAILED — fix the [FAIL] rows above")
        return 1
    log.info("selfcheck finished PASS=%d WARN=%d SKIP=%d — exit 0"
             % (counts["PASS"], counts["WARN"], counts["SKIP"]))
    return 0


def once(args):
    """--once: one /health probe, no phases, no mutex."""
    cfg, _note = load_config(args.config)
    token_path, token = resolve_token(cfg)
    url = str(cfg["supervisor"].get("health_url", HEALTH_URL))
    timeout = float(cfg["supervisor"].get("probe_timeout", 3.0))
    state, detail = probe_health(url, token, timeout)
    Logger().info("once probe %s -> %s (%s) token_path=%s"
                  % (url, state, detail, token_path))
    return 0 if state == "ok" else 1


def mutex_probe(args):
    """--mutex-probe: cross-process proof of the single-instance guard."""
    if not IS_WINDOWS:
        print("MUTEX_SKIP non-Windows runner — CreateMutexW unavailable")
        return 0
    name = inst_mod.mutex_name()
    try:
        handle, acquired = create_mutex(name)
    except Exception as exc:
        print("MUTEX_FAIL %s" % exc)
        return 1
    if not acquired:
        print("MUTEX_DUPLICATE another instance holds '%s' — this launch "
              "exits 0" % name)
        release_mutex(handle)
        return 0
    print("MUTEX_ACQUIRED pid=%d name=%s hold=%.1fs"
          % (os.getpid(), name, args.hold))
    try:
        time.sleep(args.hold)
    finally:
        release_mutex(handle)
    print("MUTEX_RELEASED pid=%d" % os.getpid())
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="raphael-supervisor",
        description="Raphael Windows supervisor — logon bring-up + health "
                    "watchdog (docs/PROTOCOL.md port 8765)")
    parser.add_argument("--selfcheck", action="store_true",
                        help="run environment self-tests and exit")
    parser.add_argument("--once", action="store_true",
                        help="single /health probe then exit (0 = healthy)")
    parser.add_argument("--mutex-probe", action="store_true",
                        help="acquire/detect the single-instance mutex, exit")
    parser.add_argument("--hold", type=float, default=5.0,
                        help="seconds to hold the mutex in --mutex-probe mode")
    parser.add_argument("--config", default=str(CONFIG_PATH),
                        help="path to config.yaml")
    return parser.parse_args(argv)


# --------------------------------------------------------------------------
# Pid liveness across sides (Bug G, Wave 3): WSL and Windows have SEPARATE
# pid namespaces — `os.kill` on a Windows pid from inside WSL says "dead"
# while the process lives (that made `raphael stop` call a live supervisor
# dead), and vice versa pidfiles can go stale across restarts.
# --------------------------------------------------------------------------
def _on_wsl() -> bool:
    """True when running inside WSL (Linux with the Microsoft kernel tag)."""
    if IS_WINDOWS:
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        with open("/proc/sys/kernel/osrelease", "r") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def _windows_pid_alive(pid) -> bool:
    """Is `pid` a live WINDOWS process? Checked from WSL via tasklist.exe
    interop (never os.kill — wrong namespace). False when tasklist itself
    is unavailable (caller decides how to report 'unknown')."""
    try:
        proc = subprocess.run(
            ["tasklist.exe", "/FI", "PID eq %d" % int(pid), "/NH"],
            capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    out = _decode(proc.stdout) + _decode(proc.stderr)
    if proc.returncode != 0:
        return False
    # alive: "name.exe   1234 Console   ..."  dead: "INFO: No tasks..."
    return ("No tasks" not in out) and (str(pid) in out.split())


def _linux_pid_exists(pid) -> bool:
    """POSIX-namespace probe only (os.kill is meaningless across the
    WSL/Windows pid boundary — see _pid_exists)."""
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _pid_exists(pid: int) -> bool:
    """Side-correct liveness. On WSL a pid MAY be either a local Linux pid
    (degraded supervisor/CLI runs inside WSL) or a Windows pid (the real
    Windows supervisor) — probe both namespaces; a hit in EITHER is alive."""
    pid = int(pid)
    if IS_WINDOWS:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    if _on_wsl():
        if _linux_pid_exists(pid):
            return True                      # local Linux pid
        return _windows_pid_alive(pid)       # maybe the Windows supervisor
    return _linux_pid_exists(pid)


# --------------------------------------------------------------------------
# Supervisor pidfile with a side marker: content = "<pid>\nside=<windows|linux>"
# (Bug G: a bare pid is ambiguous across the WSL/Windows boundary — the
# marker says which namespace to probe/kill in. Legacy single-line files
# still parse: side=None -> caller probes conservatively.)
# --------------------------------------------------------------------------
def write_supervisor_pidfile(pid, side=None):
    path = inst_mod.supervisor_pidfile()
    side = side or ("windows" if IS_WINDOWS else "linux")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("%d\nside=%s\n" % (int(pid), side), encoding="utf-8")
        return path
    except OSError as exc:
        sys.stderr.write("supervisor: pidfile %s not written: %s\n"
                         % (path, exc))
        return None


def read_supervisor_pidfile():
    """-> (pid:int|None, side:'windows'|'linux'|None, path, stale:bool)."""
    path = inst_mod.supervisor_pidfile()
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").split()
    except OSError:
        return None, None, path, False
    if not raw:
        return None, None, path, True
    try:
        pid = int(raw[0])
    except ValueError:
        return None, None, path, True          # corrupt -> stale
    side = None
    for tok in raw[1:]:
        if tok.startswith("side="):
            side = tok.split("=", 1)[1].strip() or None
    return pid, side, path, False


def _write_supervisor_pidfile():
    """run/supervisor[_<instance>].pid — lets `raphael stop` find us.

    Written ONLY after the mutex is acquired (a second launch exits 0
    before this and must never clobber the live supervisor's pidfile).
    Under the watchdog (Wave 4 crash recovery) the CHILD records the
    PARENT's pid — the tree-kill root — so `raphael stop` takes out the
    whole watchdog+child tree in one go. Best effort: never fatal.
    """
    pid = int(os.environ.get(_WATCHDOG_PARENT_ENV) or os.getpid())
    return write_supervisor_pidfile(pid)


def _remove_supervisor_pidfile(path):
    if path:
        try:
            path.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------
# Crash recovery — supervisor self-restart (Wave 4 resilience)
# --------------------------------------------------------------------------
# The default run entry becomes a thin WATCHDOG parent: it spawns the real
# bring-up as its child and respawns the child if it ever dies. Wiring is
# UNCHANGED (Task Scheduler still runs `pythonw supervisor/main.py` —
# AGENT_RULES §12 forbids task edits; `raphael stop` still works because
# the child's pidfile points at the parent/tree root). Opt out with
# RAPHAEL_WATCHDOG=0 (CI, tests, degraded runs). A crash of the PARENT
# itself still needs an external relaunch (logon task) — a watchdog cannot
# resurrect itself; that boundary is documented, not hidden.
_WATCHDOG_CHILD_ENV = "RAPHAEL_SUPERVISOR_CHILD"
_WATCHDOG_PARENT_ENV = "RAPHAEL_SUPERVISOR_PARENT_PID"
_WATCHDOG_NAP = 2.0            # Rule 15: respawn fast, no long limbo
_WATCHDOG_RAPID_LIFE = 10.0    # child living < this counts as a crash
_WATCHDOG_MAX_RAPID = 5        # crash-loop guard: give up loudly


def _spawn_child(args):
    """Spawn the real bring-up as our child (hidden, console-less)."""
    exe = sys.executable
    if IS_WINDOWS:
        pyw = Path(sys.executable).with_name("pythonw.exe")
        if pyw.is_file():
            exe = str(pyw)
    env = dict(os.environ)
    env[_WATCHDOG_CHILD_ENV] = "1"
    env[_WATCHDOG_PARENT_ENV] = str(os.getpid())
    kwargs = {"cwd": str(REPO_ROOT), "stdin": subprocess.DEVNULL,
              "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "env": env}
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x08000000      # CREATE_NO_WINDOW
    try:
        return subprocess.Popen(
            [exe, str(Path(__file__).resolve()), "--config",
             str(args.config)], **kwargs)
    except OSError as exc:
        sys.stderr.write("watchdog: child spawn failed: %s\n" % exc)
        return None


def _watchdog_loop(log, spawn, nap=None, stop=None,
                   rapid_life=_WATCHDOG_RAPID_LIFE,
                   max_rapid=_WATCHDOG_MAX_RAPID):
    """Respawn the child on unexpected exit; give up after a crash loop.

    `spawn()` -> child-like with .wait() (None = spawn failed, counted as
    an instant crash). `stop()` -> True ends the loop cleanly (SIGTERM
    forwarding). Returns 0 = clean stop, 1 = gave up (crash loop).
    """
    nap = nap if nap is not None else (lambda s: time.sleep(s))
    stop = stop or (lambda: False)
    rapid = 0
    while not stop():
        child = spawn()
        t0 = time.monotonic()
        if child is None:
            rc, life = "spawn-failed", 0.0
        else:
            rc = child.wait()
            life = time.monotonic() - t0
        if stop():
            log.info("watchdog: child stopped on request (rc=%s)" % rc)
            return 0
        rapid = rapid + 1 if life < rapid_life else 0
        if rapid >= max_rapid:
            log.error("watchdog: child crashed %d times in a row (each "
                      "alive < %.0fs, rc=%s) — giving up; fix the cause "
                      "then relaunch (RAPHAEL_WATCHDOG=0 runs bare)"
                      % (rapid, rapid_life, rc))
            return 1
        log.warn("watchdog: child exited rc=%s after %.1fs — respawning "
                 "in %.1fs (crash %d/%d)"
                 % (rc, life, _WATCHDOG_NAP, rapid, max_rapid))
        nap(_WATCHDOG_NAP)
    return 0


def watchdog_main(args):
    """Watchdog parent: spawn + supervise the real bring-up child."""
    log = Logger()
    log.info("watchdog: crash-recovery parent pid=%d starting — child "
             "runs the bring-up (RAPHAEL_WATCHDOG=0 disables)" % os.getpid())
    state = {"child": None}
    stop_flag = {"on": False}

    def _on_term(signum, _frame):
        stop_flag["on"] = True
        child = state["child"]
        if child is not None and child.poll() is None:
            try:
                child.terminate()               # child's own SIGTERM path
            except OSError:
                pass

    try:
        signal.signal(signal.SIGTERM, _on_term)
        signal.signal(signal.SIGINT, _on_term)
    except (ValueError, OSError, AttributeError):
        pass

    def spawn():
        child = _spawn_child(args)
        state["child"] = child
        return child

    rc = _watchdog_loop(log, spawn=spawn, stop=lambda: stop_flag["on"])
    child = state["child"]
    if child is not None and child.poll() is None:
        try:
            child.terminate()
        except OSError:
            pass
    log.info("watchdog: exiting (rc=%d)" % rc)
    return rc


def main(argv=None):
    args = parse_args(argv)
    if args.selfcheck:
        return selfcheck(args)
    if args.once:
        return once(args)
    if args.mutex_probe:
        return mutex_probe(args)

    # Wave 4 crash recovery: the default run entry becomes the watchdog
    # parent (spawns the real bring-up as its child). Child env set, or
    # RAPHAEL_WATCHDOG=0 -> fall through to the real run below (unchanged).
    if (not os.environ.get(_WATCHDOG_CHILD_ENV)
            and os.environ.get("RAPHAEL_WATCHDOG", "1").strip() != "0"):
        return watchdog_main(args)

    log = Logger()
    log.info("supervisor starting pid=%d python=%s platform=%s"
             % (os.getpid(), sys.version.split()[0], sys.platform))

    # SIGTERM = CLEAN shutdown (finally: keepalive terminate, supervisor
    # pidfile removal, mutex release). Default SIGTERM would skip `finally`
    # entirely — `raphael stop` sends SIGTERM on WSL/Linux.
    try:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    except (ValueError, OSError, AttributeError):
        pass

    # ---- single-instance guard (second launch exits 0) ------------------
    mutex = inst_mod.mutex_name()          # Raphael_Supervisor[_<instance>]
    mutex_handle = None
    if IS_WINDOWS:
        try:
            mutex_handle, acquired = create_mutex(mutex)
        except Exception as exc:
            log.error("CreateMutexW failed: %s" % exc)
            return 1
        if not acquired:
            log.info("another supervisor instance already running (mutex "
                     "'%s') — second launch exits 0" % mutex)
            release_mutex(mutex_handle)
            return 0
        log.info("single-instance mutex acquired (%s)" % mutex)
    else:
        log.warn("non-Windows runner — single-instance mutex unavailable; "
                 "continuing in degraded mode")

    sup_pidfile = _write_supervisor_pidfile()
    if sup_pidfile:
        log.info("supervisor pidfile: %s" % sup_pidfile)

    try:
        cfg, note = load_config(args.config)
    except ValueError as exc:
        # fail-closed instance derivation (unknown RAPHAEL_INSTANCE without
        # RAPHAEL_PORT) — never guess a port, never collide with main
        log.error("config rejected: %s" % exc)
        return 1
    log.info(note)
    paths = cfg["paths"]
    token_path, token = resolve_token(cfg)
    log.info("config: instance=%s profile=%s distro=%s wsl_user=%s "
             "brain_unit=%s orb_dir=%s body_cmd=%s port=%s token_path=%s"
             % (cfg.get("instance"), active_profile(cfg), paths["distro"],
                paths["wsl_user"], paths["brain_unit"], paths["orb_dir"],
                paths["body_cmd"], paths.get("brain_port"), token_path))
    if not token:
        log.warn("token file missing at %s — probes will omit the %s header "
                 "(run scripts/token-gen.sh)"
                 % (token_path, TOKEN_HEADER))

    hooks = EventHooks()
    hooks.start(log)
    procs = {}
    exit_code = 0
    try:
        if IS_WINDOWS:
            log.info("phase 1: launching orb FIRST, then body")
            procs["orb"] = launch_orb(cfg, log)
            procs["body"] = launch_body(cfg, log)
            log.info("phase 2: WSL bring-up")
            procs["keepalive"] = start_keepalive(cfg, log)
            bring_up_wsl(cfg, log, procs)
            procs["relay"] = start_brain_relay(cfg, log)
        else:
            log.warn("non-Windows runner — phases 1/2 (orb/body/WSL "
                     "bring-up) skipped; health loop only")
        run_health_loop(cfg, log, hooks, procs)
    except KeyboardInterrupt:
        log.info("interrupted (Ctrl+C) — shutting down")
    finally:
        hooks.stop()
        keepalive = procs.get("keepalive")
        if keepalive is not None and keepalive.poll() is None:
            try:
                keepalive.terminate()
                log.info("wsl-keepalive terminated")
            except OSError:
                pass
        _remove_supervisor_pidfile(sup_pidfile)
        release_mutex(mutex_handle)
        log.info("supervisor exiting (code=%d)" % exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
