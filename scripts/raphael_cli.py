#!/usr/bin/env python3
"""raphael — the Raphael stack CLI (thin client over brain-core's REST API).

Windows:   scripts\\raphael.cmd  <command>       (wraps this file)
WSL:       scripts/raphael <command>             (wraps this file)
Direct:    python3 scripts/raphael_cli.py <command>

Commands (Wave-2 task: status/start/stop/restart/pause/resume/private/
logs/jobs/cancel/say/selftest — REST only, no new PROTOCOL frames):

  status               GET /health + /status (pretty)
  start                Windows: spawn the supervisor (full bring-up: orb,
                       body, brain, relay). WSL: spawn the brain process
                       (loopback, instance-aware). Idempotent.
  stop                 stop supervisor (pidfile tree) + brain (pidfile +
                       cmdline verified) + orphan body; verify health down.
                       Idempotent ("nothing running" -> 0).
  restart              stop, then start; waits for /health.
  pause | resume       POST /control {action: pause|resume, persist:true}
  private on|off       POST /control {action: private_on|private_off}
  logs [name] [-n N] [-f]   tail a supervisor-side log (instance-aware):
                       supervisor|brain|body|orb|wsl-relay|wsl-keepalive
  jobs [job_id]        GET /jobs  or  GET /jobs/{id}  (--raw for JSON;
                       --wait polls one job to a terminal state —
                       simulation supervision, --timeout budget)
  cancel <id> [--gui]  POST /jobs/{id}/cancel {scope: full|gui}
  say <text...> [--gui]  POST /jobs {text, source:text} — typed input
                       (--gui also takes the input lock for screen-driving
                       typed commands)
  selftest             supervisor --selfcheck (env self-test)
  tier [name] [--force]  show/set persona.tier in config.d (Wave 5 safe
                       runtime switch: fail-closed validation, active-jobs
                       guard, single-spawner brain recycle so the running
                       supervisor never double-respawns)

Exit codes: 0 = ok, 1 = command failed (HTTP error/bad usage),
            2 = brain unreachable.
Token: read via supervisor.resolve_token (path printed, VALUE never shown).
Instance: everything derives from RAPHAEL_INSTANCE/RAPHAEL_PORT (§d).
Stdlib only; never prints secrets (AGENT_RULES §7).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]      # scripts/ -> repo root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supervisor import instance as inst_mod      # noqa: E402
from supervisor import main as sup               # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_DOWN = 0, 1, 2
IS_WINDOWS = os.name == "nt"
LOG_NAMES = ("supervisor", "brain", "body", "orb", "wsl-relay",
             "wsl-keepalive")
CREATE_NO_WINDOW = 0x08000000


class Ctx:
    """Resolved config + endpoint for one CLI invocation."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.instance = cfg.get("instance") or inst_mod.instance_name()
        self.port = int(cfg["paths"].get("brain_port") or 8765)
        health = str(cfg["supervisor"].get("health_url", sup.HEALTH_URL))
        self.base = health.rsplit("/health", 1)[0]
        self.token_path, self.token = sup.resolve_token(cfg)
        # test hooks (defaults = production values)
        self.poll_tries = 12
        self.poll_delay = 1.5

    @property
    def logger(self):
        return sup.Logger(path=inst_mod.log_path("supervisor"), echo=False)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def api(ctx, method, path, body=None, timeout=10.0):
    """-> (status_code | None, payload | error_string).

    None status = connection-level failure (brain down) -> EXIT_DOWN.
    """
    headers = {"User-Agent": "raphael-cli/1.0"}
    if ctx.token:
        headers[sup.TOKEN_HEADER] = ctx.token
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(ctx.base + path, data=data, headers=headers,
                                 method=method)
    try:
        with sup._OPENER.open(req, timeout=timeout) as resp:
            code = int(getattr(resp, "status", None) or resp.getcode())
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        code = int(exc.code)
        raw = exc.read().decode("utf-8", "replace")
    except Exception as exc:                       # refused/timeout/DNS
        return None, "%s: %s" % (type(exc).__name__, exc)
    try:
        payload = json.loads(raw) if raw.strip() else None
    except ValueError:
        payload = raw
    return code, payload


def _auth_or_down(ctx, code, payload):
    """Shared early-return: (message lines, exit code) or None to continue."""
    if code is None:
        return (["brain: unreachable at %s (%s)" % (ctx.base, payload),
                 "hint: raphael start  (or the supervisor is not running)"],
                EXIT_DOWN)
    if code in (401, 403):
        return (["brain: reachable but TOKEN REJECTED (HTTP %d) at %s"
                 % (code, ctx.base),
                 "token file: %s (value not shown)" % ctx.token_path],
                EXIT_FAIL)
    if code >= 500:
        return (["brain: server error (HTTP %d)" % code], EXIT_FAIL)
    return None


def _print(lines):
    for line in lines:
        print(line)


# --------------------------------------------------------------------------
# Commands — REST
# --------------------------------------------------------------------------
def cmd_status(ctx, args):
    code, payload = api(ctx, "GET", "/health")
    early = _auth_or_down(ctx, code, payload)
    if early:
        _print(early[0])
        return early[1]
    if code != 200:
        print("brain: unhealthy (HTTP %d)" % code)
        return EXIT_FAIL
    print("brain: ok @ %s  instance=%s port=%d"
          % (ctx.base, ctx.instance, ctx.port))
    code, st = api(ctx, "GET", "/status")
    early = _auth_or_down(ctx, code, st)
    if early:
        _print(early[0])
        return early[1]
    if code == 200 and isinstance(st, dict):
        for key, val in sorted(st.items()):
            if isinstance(val, dict):
                inner = ", ".join("%s=%s" % (k, v)
                                  for k, v in sorted(val.items()))
                print("  %-18s %s" % (key, inner))
            else:
                print("  %-18s %s" % (key, val))
    return EXIT_OK


def cmd_pause(ctx, args):
    return _control(ctx, "pause")


def cmd_resume(ctx, args):
    return _control(ctx, "resume")


def cmd_private(ctx, args):
    return _control(ctx, "private_on" if args.state == "on"
                    else "private_off")


def _control(ctx, action):
    code, payload = api(ctx, "POST", "/control",
                        {"action": action, "persist": True})
    early = _auth_or_down(ctx, code, payload)
    if early:
        _print(early[0])
        return early[1]
    if code == 200 and isinstance(payload, dict):
        bits = ["%s -> mode=%s" % (action, payload.get("mode"))]
        if "paused" in payload:
            bits.append("paused=%s" % payload["paused"])
        if payload.get("persisted"):
            bits.append("persisted")
        print(" ".join(bits))
        return EXIT_OK
    print("control %s failed (HTTP %s): %s"
          % (action, code, payload if isinstance(payload, str)
             else json.dumps(payload)))
    return EXIT_FAIL


def cmd_jobs(ctx, args):
    if getattr(args, "wait", False):
        return _wait_job(ctx, args)
    if args.job_id:
        code, job = api(ctx, "GET", "/jobs/%s" % args.job_id)
        early = _auth_or_down(ctx, code, job)
        if early:
            _print(early[0])
            return early[1]
        if code == 200:
            print(json.dumps(job, indent=2, ensure_ascii=False))
            return EXIT_OK
        print("job %s: HTTP %s: %s" % (args.job_id, code, job))
        return EXIT_FAIL
    code, jobs = api(ctx, "GET", "/jobs")
    early = _auth_or_down(ctx, code, jobs)
    if early:
        _print(early[0])
        return early[1]
    if code != 200 or not isinstance(jobs, list):
        print("jobs: HTTP %s: %s" % (code, jobs))
        return EXIT_FAIL
    if args.raw:
        print(json.dumps(jobs, indent=2, ensure_ascii=False))
        return EXIT_OK
    if not jobs:
        print("no jobs")
        return EXIT_OK
    print("%-24s %-12s %-9s %5s  %s" % ("JOB", "STATUS", "STAGE", "PROG",
                                        "TASK"))
    for j in jobs:
        task = " ".join(str(j.get("task") or j.get("text") or "").split())
        if len(task) > 46:
            task = task[:45] + "…"
        print("%-24s %-12s %-9s %5s  %s"
              % (j.get("job", "?"), j.get("status", "?"),
                 j.get("stage", "-"),
                 "%.0f%%" % (100 * float(j.get("progress") or 0.0)),
                 task))
    return EXIT_OK


def _wait_job(ctx, args):
    """Wave 5 simulation supervision: poll one job to a terminal state.
    Rule 15: tight 0.4 s polls; prints a line on every meaningful change."""
    if not args.job_id:
        print("jobs --wait needs a job id")
        return EXIT_FAIL
    deadline = time.monotonic() + max(1.0, float(args.timeout))
    last_key = None
    saw_confirm_hint = False
    while True:
        code, job = api(ctx, "GET", "/jobs/%s" % args.job_id, timeout=5.0)
        if code is None:
            print("brain unreachable while waiting (%s)" % job)
            return EXIT_DOWN
        if code in (401, 403):
            print("TOKEN REJECTED while waiting — token: %s" % ctx.token_path)
            return EXIT_FAIL
        if code == 404:
            print("job %s not found" % args.job_id)
            return EXIT_FAIL
        if code != 200 or not isinstance(job, dict):
            print("GET /jobs/%s -> HTTP %s: %s"
                  % (args.job_id, code, job))
            return EXIT_FAIL
        status = str(job.get("status") or "?")
        stage = str(job.get("stage") or "-")
        prog = float(job.get("progress") or 0.0)
        key = (status, stage, int(prog * 10))
        if key != last_key:
            last_key = key
            print("  %-12s %-9s %3.0f%%" % (status, stage, 100 * prog))
            if status == "awaiting_confirm" and not saw_confirm_hint:
                saw_confirm_hint = True
                print("  (waiting for user confirmation — approve/decline "
                      "in the app or CLI)")
        if status in TERMINAL_STATUSES:
            print("job %s: %s" % (args.job_id, status))
            if status == "done":
                result = job.get("result")
                if isinstance(result, str) and result.strip():
                    out = " ".join(result.split())
                    print("result: %s" % (out[:400] + "…"
                                          if len(out) > 400 else out))
                return EXIT_OK
            err = job.get("error_code")
            if err:
                print("error: %s" % err)
            return EXIT_FAIL
        if time.monotonic() >= deadline:
            print("timeout after %.0fs waiting for %s (last: %s/%s)"
                  % (float(args.timeout), args.job_id, status, stage))
            return EXIT_FAIL
        time.sleep(0.4)


def cmd_cancel(ctx, args):
    scope = "gui" if args.gui else "full"
    code, payload = api(ctx, "POST", "/jobs/%s/cancel" % args.job_id,
                        {"scope": scope})
    early = _auth_or_down(ctx, code, payload)
    if early:
        _print(early[0])
        return early[1]
    if code == 200 and isinstance(payload, dict) and payload.get("cancelled"):
        job = payload.get("job") or {}
        print("cancelled %s (scope=%s) status=%s"
              % (args.job_id, scope, job.get("status")))
        return EXIT_OK
    print("cancel %s failed (HTTP %s): %s"
          % (args.job_id, code, payload if isinstance(payload, str)
             else json.dumps(payload)))
    return EXIT_FAIL


def cmd_say(ctx, args):
    text = " ".join(args.text).strip()
    if not text:
        print("say: empty text")
        return EXIT_FAIL
    body = {"text": text, "source": "text", "input_lock": bool(args.gui)}
    code, payload = api(ctx, "POST", "/jobs", body)
    early = _auth_or_down(ctx, code, payload)
    if early:
        _print(early[0])
        return early[1]
    if code == 200 and isinstance(payload, dict):
        job_id = payload.get("job_id", "?")
        status = (payload.get("job") or {}).get("status", "?")
        print("submitted %s (status=%s%s)"
              % (job_id, status, ", input lock" if args.gui else ""))
        return EXIT_OK
    print("say failed (HTTP %s): %s" % (code, payload))
    return EXIT_FAIL


def cmd_logs(ctx, args):
    path = inst_mod.log_path(args.name)
    if not path.is_file():
        print("no log at %s (instance=%s — nothing started yet?)"
              % (path, ctx.instance))
        return EXIT_FAIL
    if args.follow:
        print("==> following %s (Ctrl+C to stop) <==" % path)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(0, os.SEEK_END)
                while True:
                    line = fh.readline()
                    if line:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                    else:
                        time.sleep(0.5)
        except KeyboardInterrupt:
            print()
            return EXIT_OK
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = deque(fh, maxlen=max(1, args.lines))
    if not lines:
        print("%s is empty" % path)
        return EXIT_OK
    print("==> %s (last %d) <==" % (path, len(lines)))
    for line in lines:
        sys.stdout.write(line if line.endswith("\n") else line + "\n")
    return EXIT_OK


def cmd_selftest(ctx, args):
    print("raphael CLI: instance=%s port=%d token=%s"
          % (ctx.instance, ctx.port, ctx.token_path))
    proc = subprocess.run(
        [sys.executable, str(ROOT / "supervisor" / "main.py"), "--selfcheck"],
        cwd=str(ROOT))
    return proc.returncode


# --------------------------------------------------------------------------
# Commands — local lifecycle (start/stop/restart)
# --------------------------------------------------------------------------
def _pid_exists(pid):
    return sup._pid_exists(int(pid))


def _kill_windows_tree(pid, label, actions):
    """Graceful tree kill first, forced after a grace period.

    Uses taskkill.exe explicitly so it works BOTH on Windows and from
    inside WSL via interop (Bug G: stopping a Windows supervisor from the
    WSL-side CLI)."""
    tk = "taskkill.exe"
    try:
        subprocess.run([tk, "/PID", str(pid), "/T"],
                       capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        actions.append("%s kill failed: %s" % (label, exc))
        return False
    for _ in range(8):
        if not _pid_exists(pid):
            actions.append("%s pid=%s stopped" % (label, pid))
            return True
        time.sleep(0.5)
    try:
        subprocess.run([tk, "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass
    alive = _pid_exists(pid)
    if not alive:
        actions.append("%s pid=%s stopped (forced)" % (label, pid))
    return not alive


def _verify_windows_supervisor(pid):
    """Legacy single-line pidfile seen from WSL: is this Windows pid REALLY
    our supervisor? (Never taskkill an unverified pid — Bug G safety.)
    True / False / None = unknown (powershell unavailable)."""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter "
             "'ProcessId=%d').CommandLine" % int(pid)],
            capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    text = sup._decode(proc.stdout).strip()
    if not text or text.lower() == "none":
        return False                          # no such process anymore
    low = text.lower()
    return "supervisor" in low and "main.py" in low


def _spawn_supervisor(ctx):
    """Windows: launch the supervisor (full bring-up) detached."""
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pyw) if pyw.is_file() else sys.executable
    env = dict(os.environ)
    env["RAPHAEL_INSTANCE"] = ctx.instance
    kwargs = {"cwd": str(ROOT), "stdin": subprocess.DEVNULL,
              "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "env": env}
    if IS_WINDOWS:
        kwargs["creationflags"] = CREATE_NO_WINDOW
    proc = subprocess.Popen(
        [exe, str(ROOT / "supervisor" / "main.py")], **kwargs)
    print("supervisor spawn requested (pid=%d, instance=%s) — bringing up "
          "orb/body/brain/relay" % (proc.pid, ctx.instance))


def _spawn_brain_local(ctx):
    """WSL/Linux: spawn the brain process directly (loopback, instance-aware)."""
    vpy = ROOT / "brain" / ".venv" / "bin" / "python"
    if not vpy.is_file():
        print("brain venv missing (%s) — cannot start" % vpy)
        return False
    pidfiles = inst_mod.wsl_pidfiles(ctx.instance)
    pidfile = pidfiles[0]
    pidfile_env = pidfile.replace("~", "$HOME", 1) if pidfile.startswith("~") \
        else pidfile
    data_dir = inst_mod.wsl_data_dir(ctx.instance)
    script = (
        'export RAPHAEL_INSTANCE=%s RAPHAEL_PORT=%d RAPHAEL_PIDFILE="%s"; '
        'mkdir -p %s; echo $$ > %s; cd %s && exec %s -m uvicorn '
        'brain.app:app --host 127.0.0.1 --port %d'
        % (shlex.quote(ctx.instance), ctx.port, pidfile_env, data_dir,
           pidfile, shlex.quote(str(ROOT)), shlex.quote(str(vpy)), ctx.port))
    log_path = inst_mod.log_path("brain")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    out = open(log_path, "ab", buffering=0)
    try:
        subprocess.Popen(["sh", "-c", script], cwd=str(ROOT),
                         stdin=subprocess.DEVNULL, stdout=out,
                         stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        out.close()
    print("brain spawn requested (uvicorn 127.0.0.1:%d, instance=%s, "
          "pidfile=%s)" % (ctx.port, ctx.instance, pidfile))
    return True


def _wait_health(ctx, want):
    """Poll /health until it matches `want` ('up' -> 200/401, 'down' -> conn fail)."""
    deadline_tries = ctx.poll_tries
    for _ in range(max(1, deadline_tries)):
        code, _payload = api(ctx, "GET", "/health", timeout=3.0)
        if want == "up" and code in (200, 401):
            return code
        if want == "down" and code is None:
            return None
        time.sleep(ctx.poll_delay)
    code, _payload = api(ctx, "GET", "/health", timeout=3.0)
    return code if want == "up" else (None if code is None else code)


def cmd_start(ctx, args):
    code, payload = api(ctx, "GET", "/health", timeout=3.0)
    if code in (200, 401):
        note = " (note: token rejected)" if code == 401 else ""
        print("already running%s @ %s" % (note, ctx.base))
        return EXIT_OK
    if IS_WINDOWS:
        _spawn_supervisor(ctx)
    else:
        if not _spawn_brain_local(ctx):
            return EXIT_FAIL
    final = _wait_health(ctx, "up")
    if final == 200:
        print("healthy @ %s" % ctx.base)
        return EXIT_OK
    if final == 401:
        print("started but TOKEN REJECTED (HTTP 401) — token file: %s"
              % ctx.token_path)
        return EXIT_FAIL
    print("started but not healthy after %.0fs — check logs (%s)"
          % (ctx.poll_tries * ctx.poll_delay,
             inst_mod.log_path("supervisor")))
    return EXIT_DOWN


def _stop_supervisor_pid(pid, side, actions):
    """Side-aware supervisor stop (Bug G). Returns 'stopped'|'stale'|'alive'
    |'refused'. `side` comes from the pidfile marker (new format); legacy
    single-line files (side=None) are probed conservatively — a Windows pid
    is only taskkilled after its CommandLine is verified as our supervisor."""
    # marker says linux: trust it (degraded supervisor runs inside WSL)
    if side == "linux" or (side is None and not IS_WINDOWS
                           and sup._linux_pid_exists(pid)):
        try:
            os.kill(pid, 15)                  # SIGTERM -> clean finally
            actions.append("supervisor pid=%s signaled (SIGTERM)" % pid)
        except OSError as exc:
            actions.append("supervisor kill failed: %s" % exc)
        for _ in range(10):
            if not _pid_exists(pid):
                return "stopped"
            time.sleep(0.3)
        return "alive" if _pid_exists(pid) else "stopped"
    # windows pid (marker, Windows host, or WSL-visible leftover)
    if IS_WINDOWS or side == "windows":
        return "stopped" if _kill_windows_tree(pid, "supervisor",
                                               actions) else "alive"
    if side is None:
        if not _pid_exists(pid):
            return "stale"
        verdict = _verify_windows_supervisor(pid)
        if verdict is not True:
            actions.append(
                "WARNING: legacy pidfile pid=%s — Windows identity not "
                "verified (%s); REFUSING taskkill (Bug G safety). Remove "
                "%s manually if it is stale."
                % (pid, {None: "unknown", False: "not our supervisor"}[
                    verdict], inst_mod.supervisor_pidfile()))
            return "refused"
    return "stopped" if _kill_windows_tree(pid, "supervisor",
                                           actions) else "alive"


def cmd_stop(ctx, args):
    actions = []
    # 1. supervisor first (the watchdog must not respawn anything) —
    #    side-aware pidfile handling (Bug G: WSL cannot see Windows pids
    #    and vice versa; stale pids must not fake a 'dead' supervisor).
    pid, side, sup_pidfile, stale = sup.read_supervisor_pidfile()
    if stale:
        actions.append("supervisor pidfile corrupt/empty — removed")
        try:
            sup_pidfile.unlink()
        except OSError:
            pass
    elif pid:
        outcome = _stop_supervisor_pid(pid, side, actions)
        if outcome == "stale":
            actions.append("supervisor pidfile stale (pid %s dead) — removed"
                           % pid)
            try:
                sup_pidfile.unlink()
            except OSError:
                pass
        elif outcome == "alive":
            print("supervisor pid=%s still alive — investigate manually" % pid)

    # 2. brain (pidfile + ss-port resolved + cmdline verified)
    if sup.stop_brain(ctx.cfg, ctx.logger):
        actions.append("brain stopped (pidfile/ss/cmdline verified)")

    # 3. WSL side: orb (cwd-verified), this instance's relay helper,
    #    keepalive loops — zero-survivor report (Bug G). The line joins the
    #    action list only when something was found/stopped (keeps the
    #    idempotent "nothing running" path honest).
    wsl_clean = sup.stop_wsl_side(ctx.cfg, ctx.logger)
    if not wsl_clean:
        actions.append("wsl-side teardown: LEFTOVERS (see supervisor log)")
    elif actions:
        actions.append("wsl-side teardown: clean")

    # 4. orphan body (Windows pid — probe works from both hosts now)
    bpid = sup._external_body_pid()
    if bpid and _pid_exists(bpid):
        _kill_windows_tree(bpid, "body", actions)

    # 5. verify the endpoint actually went down AND wsl side is clean
    down = _wait_health(ctx, "down")
    for line in actions:
        print(line)
    if down is None:
        if not wsl_clean:
            print("WARNING: %s is down but wsl-side leftovers remain — "
                  "see logs/supervisor.log (Bug G report)" % ctx.base)
            return EXIT_FAIL
        if not actions:
            print("nothing running (idempotent stop) — %s already down"
                  % ctx.base)
        else:
            print("stack stopped — %s refusing connections, wsl side clean"
                  % ctx.base)
        return EXIT_OK
    print("WARNING: %s still answering (HTTP %s) after stop — check "
          "logs/supervisor.log and running processes" % (ctx.base, down))
    return EXIT_FAIL


def cmd_restart(ctx, args):
    rc = cmd_stop(ctx, args)
    if rc != EXIT_OK:
        print("restart: stop did not fully succeed — aborting start")
        return rc
    return cmd_start(ctx, args)


# --------------------------------------------------------------------------
# Wave 5 — persona tier runtime switch (safe restart semantics) +
#          simulation job supervision (jobs --wait)
# --------------------------------------------------------------------------
TIER_FILE = ROOT / "config.d" / "evolution-persona.yaml"
VALID_TIERS = ("great_sage", "raphael", "ciel")
ACTIVE_STATUSES = ("queued", "running", "awaiting_confirm")
TERMINAL_STATUSES = ("done", "failed", "cancelled", "interrupted")
_TIER_LINE = re.compile(r"^([ \t]*tier:[ \t]*)([^\s#]+)([ \t]*(?:#.*)?)$",
                        re.MULTILINE)


def _read_tier(path=None):
    path = Path(path) if path else TIER_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    matches = _TIER_LINE.findall(text)
    return matches[0][1] if len(matches) == 1 else None


def _write_tier(value, path=None):
    """Surgical single-line replace of persona.tier — refuses unless the
    file has EXACTLY one 'tier:' line (fail-closed, mirrors the tier
    loader's C1/C2 semantics; value must be pre-validated)."""
    path = Path(path) if path else TIER_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, "cannot read %s: %s" % (path, exc)
    if len(_TIER_LINE.findall(text)) != 1:
        return False, ("expected EXACTLY one 'tier:' line in %s — refusing "
                       "to edit (fail-closed)" % path)
    new_text, n = _TIER_LINE.subn(
        lambda m: m.group(1) + value + m.group(3), text, count=1)
    if n != 1:
        return False, "tier line rewrite failed — nothing written"
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(new_text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        return False, "cannot write %s: %s" % (path, exc)
    return True, str(path)


def _active_jobs(ctx):
    """-> (list of active jobs, error-or-None)."""
    code, jobs = api(ctx, "GET", "/jobs")
    if code is None:
        return None, "brain unreachable (%s)" % jobs
    if code != 200 or not isinstance(jobs, list):
        return None, "GET /jobs -> HTTP %s" % code
    return [j for j in jobs if j.get("status") in ACTIVE_STATUSES], None


def _recycle_brain(ctx):
    """Planned brain recycle with exactly ONE spawner: if the supervisor is
    alive its health loop respawns (the watchdog/loop owns bring-up); if
    not, the CLI spawns locally. Never both."""
    pid, _side, _path, _stale = sup.read_supervisor_pidfile()
    sup_alive = bool(pid) and _pid_exists(pid)
    if sup.stop_brain(ctx.cfg, ctx.logger):
        print("brain stopped (pidfile/ss/cmdline verified) — %s"
              % ("supervisor will respawn it" if sup_alive
                 else "respawning locally"))
    if not sup_alive:
        if not _spawn_brain_local(ctx):
            return EXIT_FAIL
    # a latched supervisor backoff may delay the respawn by one slow poll —
    # allow headroom, but keep it Rule-15 tight (max ~24 s)
    old_tries, old_delay = ctx.poll_tries, ctx.poll_delay
    ctx.poll_tries, ctx.poll_delay = 16, 1.5
    try:
        final = _wait_health(ctx, "up")
    finally:
        ctx.poll_tries, ctx.poll_delay = old_tries, old_delay
    if final == 200:
        print("healthy @ %s — config.d re-read by the new brain process "
              "(startup load)" % ctx.base)
        return EXIT_OK
    if final == 401:
        print("respawned but TOKEN REJECTED (HTTP 401) — token file: %s"
              % ctx.token_path)
        return EXIT_FAIL
    print("recycle did not become healthy within %.0fs — check logs (%s)"
          % (16 * 1.5, inst_mod.log_path("supervisor")))
    return EXIT_DOWN


def cmd_tier(ctx, args):
    if not args.name:                            # show
        tier = _read_tier()
        if tier is None:
            print("no unique persona.tier line found in %s" % TIER_FILE)
            return EXIT_FAIL
        code, _p = api(ctx, "GET", "/health", timeout=3.0)
        state = ("brain running — effective from its LAST start"
                 if code in (200, 401) else "brain not running")
        print("persona tier: %s   (%s)" % (tier, state))
        print("valid tiers: %s   edit: raphael tier <name>" %
              ", ".join(VALID_TIERS))
        return EXIT_OK
    # set
    new = args.name
    if new not in VALID_TIERS:                   # fail-closed (loader C1)
        print("tier %r not allowed — valid: %s" % (new, ", ".join(VALID_TIERS)))
        return EXIT_FAIL
    current = _read_tier()
    if current == new:
        print("persona tier already %s" % new)
        return EXIT_OK
    active, err = _active_jobs(ctx)
    if err:
        if _p_health_up(ctx):
            # reachable but /jobs broken — never switch without the guard
            print("cannot list jobs (%s) — refusing without an active-jobs "
                  "check" % err)
            if not args.force:
                print("re-run with --force to override")
                return EXIT_FAIL
            print("WARNING: --force without a job check")
        else:
            print("brain not reachable — tier will be written and applied "
                  "at the next start (%s)" % err)
    elif active:
        if not args.force:
            print("REFUSED: %d active job(s) would be interrupted by the "
                  "brain recycle:" % len(active))
            for j in active:
                print("  %s  %-18s %s" % (j.get("job"), j.get("status"),
                                          (j.get("task") or "")[:40]))
            print("finish them, or re-run with --force (they journal as "
                  "'interrupted')")
            return EXIT_FAIL
        print("WARNING: --force with %d active job(s) — they will journal "
              "as interrupted" % len(active))
    ok, detail = _write_tier(new, path=args.file)
    if not ok:
        print("tier write refused: %s" % detail)
        return EXIT_FAIL
    print("tier: %s -> %s  (%s)" % (current or "?", new, detail))
    code, _p = api(ctx, "GET", "/health", timeout=3.0)
    if code is None:
        print("brain not running — applies at next start")
        return EXIT_OK
    return _recycle_brain(ctx)


def _p_health_up(ctx):
    code, _p = api(ctx, "GET", "/health", timeout=3.0)
    return code in (200, 401)


# --------------------------------------------------------------------------
# Entry
# --------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="raphael",
        description="Raphael stack CLI (REST client + local lifecycle).",
        epilog="exit codes: 0 ok, 1 failed, 2 brain unreachable. "
               "Instance/port derive from RAPHAEL_INSTANCE (INTERFACES §d).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="health + /status snapshot")
    sub.add_parser("start", help="start supervisor (Windows) / brain (WSL)")
    sub.add_parser("stop", help="stop supervisor+brain(+body), verify down")
    sub.add_parser("restart", help="stop then start")
    sub.add_parser("pause", help="POST /control pause")
    sub.add_parser("resume", help="POST /control resume")

    pr = sub.add_parser("private", help="private mode on|off")
    pr.add_argument("state", choices=("on", "off"))

    lg = sub.add_parser("logs", help="tail a stack log")
    lg.add_argument("name", nargs="?", default="supervisor",
                    choices=LOG_NAMES)
    lg.add_argument("-n", "--lines", type=int, default=50)
    lg.add_argument("-f", "--follow", action="store_true")

    jb = sub.add_parser("jobs", help="list jobs / show one / wait on one")
    jb.add_argument("job_id", nargs="?")
    jb.add_argument("--raw", action="store_true", help="raw JSON")
    jb.add_argument("--wait", action="store_true",
                    help="poll until terminal (simulation supervision)")
    jb.add_argument("--timeout", type=float, default=300.0,
                    help="--wait budget in seconds (default 300)")

    tr = sub.add_parser(
        "tier",
        help="show/set persona tier (safe runtime switch: config.d write "
             "+ single-spawner brain recycle)")
    tr.add_argument("name", nargs="?", choices=VALID_TIERS,
                    help="great_sage | raphael | ciel (omit = show)")
    tr.add_argument("--force", action="store_true",
                    help="switch even with active jobs (they journal as "
                         "interrupted) or when /jobs is unreadable")
    tr.add_argument("--file", default=None, help=argparse.SUPPRESS)

    cn = sub.add_parser("cancel", help="cancel a job")
    cn.add_argument("job_id")
    cn.add_argument("--gui", action="store_true",
                    help="scope=gui (input lock only)")

    sy = sub.add_parser("say", help="typed input: submit text as a job")
    sy.add_argument("text", nargs="+")
    sy.add_argument("--gui", action="store_true",
                    help="also take the input lock (screen-driving input)")

    sub.add_parser("selftest", help="supervisor environment self-check")
    return p


HANDLERS = {
    "status": cmd_status, "start": cmd_start, "stop": cmd_stop,
    "restart": cmd_restart, "pause": cmd_pause, "resume": cmd_resume,
    "private": cmd_private, "logs": cmd_logs, "jobs": cmd_jobs,
    "cancel": cmd_cancel, "say": cmd_say, "selftest": cmd_selftest,
    "tier": cmd_tier,
}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        cfg, _note = sup.load_config()
    except Exception as exc:                       # noqa: BLE001
        print("raphael: config load failed: %s: %s"
              % (type(exc).__name__, exc))
        return EXIT_FAIL
    ctx = Ctx(cfg)
    try:
        return HANDLERS[args.cmd](ctx, args)
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
