"""Shadow-instance verification runs (design 01 §3; Wave-4 carry-over, unblocked
2026-10-07 when brain-core's `shadow` instance row merged: 577f09c).

Scope discipline (AGENT_RULES §5 + rule 14): a "shadow run" here is a
SUBPROCESS test run with `RAPHAEL_INSTANCE=shadow` (derived port 8911, data-dir
`~/.raphael/shadow/`) plus the instance-derivation self-check. It never spawns
a second Brain/uvicorn, never touches the live stack (main = 8765), never
opens a mic/hotkey, and never reaches a provider (test suites force their own
hermetic mocks — tests/conftest.py pins the qa suite to its own instance).

Golden transcripts are COMPARED, not executed, by `baseline.py` — transcript
replay against a live shadow Brain is a later step and needs an integrator
window (no extra server-like processes while the live stack is up).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from brain import config as cfg

REPO_ROOT = Path(__file__).resolve().parents[2]
SHADOW_INSTANCE = "shadow"
SHADOW_PORT = 8911           # INTERFACES §d row (merged 577f09c)

_ENV_DROP = ("RAPHAEL_PORT", "RAPHAEL_BIND", "RAPHAEL_PROFILE", "RAPHAEL_LOG_LEVEL")


def shadow_env(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Env for a shadow run: instance=shadow, no port/profile overrides."""
    env = dict(base if base is not None else os.environ)
    for key in _ENV_DROP:
        env.pop(key, None)
    env["RAPHAEL_INSTANCE"] = SHADOW_INSTANCE
    return env


def verify_instance_derivation(python: str = sys.executable) -> Dict[str, Any]:
    """Fail-closed check that the shadow row really derives the §d values
    (port, data-dir). Returns {'ok': bool, ...} — never raises, so a missing
    row degrades to a refused run instead of a crash."""
    code = (
        "import json;"
        "import brain.config as c;"
        "print(json.dumps({'instance': c.instance(), 'port': c.port()}))"
    )
    try:
        out = subprocess.run([python, "-c", code], cwd=str(REPO_ROOT),
                             env=shadow_env(), capture_output=True, text=True,
                             timeout=60)
    except Exception as exc:  # noqa: BLE001 — any failure = refuse
        return {"ok": False, "error": str(exc)}
    if out.returncode != 0:
        return {"ok": False, "error": (out.stderr or out.stdout).strip()}
    try:
        import json
        data = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": f"unparseable: {out.stdout!r}"}
    ok = (data.get("instance") == SHADOW_INSTANCE
          and data.get("port") == SHADOW_PORT)
    data["ok"] = ok
    if not ok:
        data["error"] = (f"expected instance={SHADOW_INSTANCE} port={SHADOW_PORT}, "
                         f"got {data}")
    return data


def run_tests(repo: Path, targets: Iterable[str],
              python: str = sys.executable, timeout: int = 900,
              extra_args: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run pytest targets under RAPHAEL_INSTANCE=shadow.

    Returns {'ok', 'rc', 'instance', 'command', 'output'} — `ok` requires rc 0
    AND a successful derivation check first (fail-closed, design 01 §6 rule 10).
    """
    repo = Path(repo)
    derived = verify_instance_derivation(python)
    targets = [str(t) for t in targets]
    cmd = [python, "-m", "pytest", "-q", *targets, *(extra_args or [])]
    result: Dict[str, Any] = {
        "instance": SHADOW_INSTANCE,
        "derivation": derived,
        "command": " ".join(cmd),
        "ok": False,
    }
    if not derived.get("ok"):
        result["error"] = "shadow instance derivation refused: " + str(derived)
        result["rc"] = None
        result["output"] = ""
        return result
    try:
        out = subprocess.run(cmd, cwd=str(repo), env=shadow_env(),
                             capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        result.update(rc=None, output=f"TIMED OUT after {timeout}s")
        return result
    except Exception as exc:  # noqa: BLE001
        result.update(rc=None, output=str(exc))
        return result
    result["rc"] = out.returncode
    result["output"] = (out.stdout + out.stderr)[-8000:]
    result["ok"] = out.returncode == 0
    return result
