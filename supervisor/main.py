#!/usr/bin/env python3
"""Raphael supervisor — Windows logon entry point, bring-up, health watchdog.

Owned by supervisor-dev (docs/ARCHITECTURE.md §2). Standard library only,
Python 3.10+ (Windows target); degrades to selfcheck/health-probe mode when run
on Linux so the WSL side can exercise it in CI.

Contract honored (docs/PROTOCOL.md):
  * Brain health  = HTTP GET http://127.0.0.1:8765/health  (port 8765)
  * Auth header   = X-Raphael-Token: <token>   (Authorization: Bearer also valid)
  * Token file    = %APPDATA%\\Raphael\\token   (WSL copy: ~/.raphael/token)
  * The token VALUE is never logged — only its path.

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
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

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
        "slow_interval": 60.0,      # PERMANENT_ERROR slow poll (spec: 60 s)
        "probe_timeout": 3.0,
        "backoff_base": 5.0,        # 5s -> 10s -> 20s ...
        "backoff_cap": 300.0,       # ... cap 300 s
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
    """`[ts] LEVEL msg` lines -> logs/supervisor.log (5 MB cap, 3 backups)."""

    def __init__(self, path=LOG_PATH, max_bytes=LOG_MAX_BYTES,
                 backups=LOG_BACKUPS, echo=True):
        self.path = Path(path)
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


def _deep_merge(base, over):
    out = dict(base)
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
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
                "body_cmd", "orb_dir", "token_win", "wsl_sudo",
                "wsl_keepalive"):
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


def load_config(path=CONFIG_PATH):
    """Return (cfg, note). Missing file -> defaults (never an error)."""
    path = Path(path)
    if not path.is_file():
        return copy.deepcopy(DEFAULT_CONFIG), (
            "config.yaml not found at %s — using built-in defaults" % path)
    text = path.read_text(encoding="utf-8", errors="replace")
    parsed = parse_config_text(text)
    cfg = _deep_merge(DEFAULT_CONFIG, parsed)
    _normalize(cfg, parsed)
    return cfg, "config.yaml loaded from %s" % path


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


def restart_brain(cfg, log, procs=None):
    if brain_run_mode(cfg) == "process":
        # Root-less recycle: pkill as the wsl_user (own process only — no
        # sudo), then respawn. pkill never matches itself; pattern targets
        # the uvicorn command line from launch_brain().
        log.info("brain process mode: recycling via pkill + respawn")
        wsl_run(cfg, "pkill", "-f", "uvicorn brain.app", timeout=10)
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
def _spawn(inner, cwd, log, label, log_file):
    """Spawn a detached child. `inner` is an argv list or a raw command string.

    UNC cwd (repo lives on \\wsl.localhost\\...) is handled via `pushd`, since
    cmd.exe refuses UNC working directories.
    """
    if isinstance(inner, str):
        inner_str = inner
        as_list = None
    else:
        as_list = list(inner)
        inner_str = (subprocess.list2cmdline(as_list) if IS_WINDOWS
                     else " ".join(shlex.quote(x) for x in as_list))
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
                      stdin=subprocess.DEVNULL)
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
    """
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
    inner = wsl_argv(cfg, "sh", "-lc",
                     "cd %s && exec %s" % (shlex.quote(wsl_dir), wsl_cmd))
    return _spawn(inner, orb_dir, log, "orb", LOG_DIR / "orb.log")


def _split_body_cmd(raw):
    parts = shlex.split(raw, posix=not IS_WINDOWS)
    if not IS_WINDOWS:
        return parts
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'"
            else p for p in parts]


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
        exe = sys.executable
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
    inner = wsl_argv(
        cfg, "sh", "-lc",
        "cd %s && exec brain/.venv/bin/python -m uvicorn brain.app:app "
        "--host 127.0.0.1 --port %d" % (shlex.quote(repo_wsl), port))
    log.info("brain process: launching uvicorn (127.0.0.1:%d) under wsl" % port)
    return _spawn(inner, REPO_ROOT, log, "brain", LOG_DIR / "brain.log")


def launch_body(cfg, log):
    """Phase 1b / watchdog: relaunch the Windows Body from paths.body_cmd."""
    exe, argv, script_path, why = body_script(cfg)
    if argv is None:
        return None
    if not Path(script_path).is_file():
        log.warn("body not ready — %s missing (owned by body-dev); "
                 "will retry when it appears" % script_path)
        return None
    return _spawn(argv, REPO_ROOT, log, "body", LOG_DIR / "body.log")


class _ExternalBody:
    """Sentinel: a body instance we did not start is running (rc==0 exit)."""

    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


def body_status(cfg, procs):
    """-> ('running'|'dead'|'unconfigured', detail)."""
    proc = procs.get("body")
    if proc is not None:
        rc = proc.poll()
        if rc is None:
            return "running", "pid=%s" % getattr(proc, "pid", "?")
        if isinstance(proc, _ExternalBody) or rc == 0:
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
                  LOG_DIR / "wsl-keepalive.log")


def _wsl_ip(cfg):
    """First IPv4 of the WSL distro (hostname -I), or None."""
    rc, out = wsl_run(cfg, "hostname", "-I", timeout=15)
    if rc != 0:
        return None
    for tok in out.replace(",", " ").split():
        if tok.count(".") == 3 and all(part.isdigit() for part in tok.split(".")):
            return tok
    return None


def start_brain_relay(cfg, log, listen_port=8765, backend_port=8766):
    """User-space TCP splice: Windows 127.0.0.1:8765 -> <wsl-ip>:8765.

    The built-in Windows->WSL localhost relay is blocked by the Hyper-V
    firewall on this machine (verified 2026-10-05: win->127.0.0.1:8765 =
    refused while win->172.x.x.x:8765 connects; NIC shows as "vEthernet
    (WSL (Hyper-V firewall))"). The admin fix is a one-liner
    (Set-NetFirewallHyperVVMSetting ... -DefaultInboundAction Allow) but
    needs elevation; this relay keeps every client on the PROTOCOL's
    localhost-only address with zero privileges. Remove when the firewall
    setting is applied (config: paths.brain_relay: false).
    """
    if not IS_WINDOWS or not cfg["paths"].get("brain_relay", True):
        return None
    import socket
    import threading

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

    def accept_loop():
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", listen_port))
            srv.listen(64)
        except OSError as exc:
            log.warn("brain relay: cannot bind 127.0.0.1:%d (%s) — relay off"
                     % (listen_port, exc))
            return
        log.info("brain relay: listening 127.0.0.1:%d -> wsl:%d (localhost "
                 "contract preserved)" % (listen_port, listen_port))
        while True:
            try:
                client, _addr = srv.accept()
            except OSError:
                return
            threading.Thread(target=handle, args=(client,),
                             daemon=True).start()

    # WSL helper leg: binds 0.0.0.0:8766 inside the VM (NAT-only), dials the
    # Brain's loopback. Detached+hidden; outlives supervisor restarts (a
    # duplicate spawn just exits on bind-conflict, logged to wsl-relay.log).
    helper_unc = REPO_ROOT / "scripts" / "wsl-relay.py"
    helper_wsl = _wsl_path(helper_unc)
    if helper_wsl:
        _spawn(wsl_argv(cfg, "python3", helper_wsl, str(backend_port),
                        str(listen_port)),
               helper_unc, log, "wsl-relay", LOG_DIR / "wsl-relay.log")
    else:
        log.warn("brain relay: cannot derive wsl path for scripts/wsl-relay.py")

    threading.Thread(target=accept_loop, daemon=True).start()
    return "relay"


def bring_up_wsl(cfg, log, procs=None):
    S = cfg["supervisor"]
    paths = cfg["paths"]
    unit = str(paths["brain_unit"])
    ollama_unit = str(paths.get("ollama_unit") or "ollama")
    if not find_wsl():
        log.error("wsl.exe not found on PATH — WSL bring-up skipped; brain "
                  "health checks will fail until WSL is available")
        return False
    log.info("phase 2: WSL bring-up distro=%s user=%s brain_unit=%s "
             "ollama_unit=%s" % (paths["distro"], paths["wsl_user"], unit,
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
    # ollama check
    ostate = wsl_state(cfg, ollama_unit, timeout=30)
    if ostate == "active":
        log.info("ollama unit '%s' is active" % ollama_unit)
    else:
        log.warn("ollama unit '%s' state=%s — issuing 'systemctl start'"
                 % (ollama_unit, ostate))
        systemctl_action(cfg, log, "start", ollama_unit, timeout=60)
        ostate = wsl_state(cfg, ollama_unit, timeout=30)
        log.info("ollama unit '%s' now %s" % (ollama_unit, ostate))
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
        orb = procs.get("orb")
        orb_txt = ("pid=%s" % orb.pid
                   if orb is not None and orb.poll() is None
                   else "not launched")
        if (not perm_brain and not perm_body and state != "down"
                and bstate == "running" and now >= heartbeat_at):
            log.info("healthy heartbeat — brain=%s body=running orb=%s"
                     % (state, orb_txt))
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

    # 1 — single-instance mutex
    if IS_WINDOWS:
        try:
            h1, acquired = create_mutex()
            if acquired:
                h2, duplicate = create_mutex()  # same-process second Create
                ok = not duplicate
                release_mutex(h2)
                release_mutex(h1)
                results.append(("single-instance mutex",
                                "PASS" if ok else "FAIL",
                                "CreateMutexW('%s') acquired; duplicate "
                                "detection %s"
                                % (MUTEX_NAME, "OK" if ok else "BROKEN")))
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
    try:
        handle, acquired = create_mutex()
    except Exception as exc:
        print("MUTEX_FAIL %s" % exc)
        return 1
    if not acquired:
        print("MUTEX_DUPLICATE another instance holds '%s' — this launch "
              "exits 0" % MUTEX_NAME)
        release_mutex(handle)
        return 0
    print("MUTEX_ACQUIRED pid=%d name=%s hold=%.1fs"
          % (os.getpid(), MUTEX_NAME, args.hold))
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


def main(argv=None):
    args = parse_args(argv)
    if args.selfcheck:
        return selfcheck(args)
    if args.once:
        return once(args)
    if args.mutex_probe:
        return mutex_probe(args)

    log = Logger()
    log.info("supervisor starting pid=%d python=%s platform=%s"
             % (os.getpid(), sys.version.split()[0], sys.platform))

    # ---- single-instance guard (second launch exits 0) ------------------
    mutex_handle = None
    if IS_WINDOWS:
        try:
            mutex_handle, acquired = create_mutex()
        except Exception as exc:
            log.error("CreateMutexW failed: %s" % exc)
            return 1
        if not acquired:
            log.info("another supervisor instance already running (mutex "
                     "'%s') — second launch exits 0" % MUTEX_NAME)
            release_mutex(mutex_handle)
            return 0
        log.info("single-instance mutex acquired (%s)" % MUTEX_NAME)
    else:
        log.warn("non-Windows runner — single-instance mutex unavailable; "
                 "continuing in degraded mode")

    cfg, note = load_config(args.config)
    log.info(note)
    paths = cfg["paths"]
    token_path, token = resolve_token(cfg)
    log.info("config: distro=%s wsl_user=%s brain_unit=%s orb_dir=%s "
             "body_cmd=%s token_path=%s"
             % (paths["distro"], paths["wsl_user"], paths["brain_unit"],
                paths["orb_dir"], paths["body_cmd"], token_path))
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
        release_mutex(mutex_handle)
        log.info("supervisor exiting (code=%d)" % exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
