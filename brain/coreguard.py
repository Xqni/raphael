"""Core Guard startup verification (SEC-7, Wave-5H audit).

Reads the Core Guard hash manifest (`{<repo-relative path>: sha256}` — the
format qa's `tests/core_guard.py` writes; coordination with evolution-persona
filed in docs/requests) and verifies the pinned files at boot. On mismatch the
brain does NOT crash-loop: it enters SAFE MODE — a visible warn Notice (flushed
to the first ui/cli session) plus an honest `/status.core_guard` block — so the
drift is unmissable without bricking diagnostics. Never raises; value-blind
logs (paths + counts only, no file contents).
"""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from . import config as appcfg

REPO_ROOT = appcfg.REPO_ROOT
DEFAULT_MANIFEST = REPO_ROOT / 'tests' / 'core_guard_manifest.json'

SAFE_MODE: Dict[str, Any] = {'active': False}
_boot_result: Optional[Dict[str, Any]] = None


def _manifest_path(explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    try:
        cfg_path = appcfg.cfg_get(appcfg.get_config(), 'core_guard.manifest', None)
        if cfg_path:
            return REPO_ROOT / str(cfg_path)
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_MANIFEST


def _tracked_under(directory: str):
    """Mirror of qa's tests/core_guard.py::_tracked_under — git ls-files
    (untracked scratch ignored) with a filesystem-walk fallback. The manifest
    format coordination note: glob keys MUST hash identically to their writer."""
    try:
        out = subprocess.run(['git', 'ls-files', '--', directory],
                             cwd=REPO_ROOT, capture_output=True, text=True,
                             timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            return [ln for ln in out.stdout.splitlines() if ln]
    except Exception:  # noqa: BLE001 — fall back to a filesystem walk
        pass
    return [str(f.relative_to(REPO_ROOT)) for f in
            sorted((REPO_ROOT / directory).rglob('*'))
            if f.is_file() and 'node_modules' not in f.parts
            and '.git' not in f.parts]


def _digest(rel: str) -> Optional[str]:
    """sha256 for a plain file, or the aggregate hash for a 'dir/**' key
    (same algorithm as tests/core_guard.py::hashes)."""
    if rel.endswith('/**'):
        base = rel[:-3]
        files = _tracked_under(base)
        if not files:
            return None
        agg = hashlib.sha256()
        for f in files:
            fp = REPO_ROOT / f
            if not fp.is_file():
                return None
            agg.update(f.encode('utf-8'))
            agg.update(hashlib.sha256(fp.read_bytes()).digest())
        return agg.hexdigest()
    fp = REPO_ROOT / rel
    if not fp.is_file():
        return None
    return hashlib.sha256(fp.read_bytes()).hexdigest()


def verify(manifest_path: Optional[Path] = None) -> Dict[str, Any]:
    """{ok, mismatched, missing, manifest} — never raises."""
    path = _manifest_path(manifest_path)
    rel = str(path.relative_to(REPO_ROOT)) if path.is_absolute() and \
        str(path).startswith(str(REPO_ROOT)) else str(path)
    try:
        if not path.is_file():
            return {'ok': False, 'reason': 'manifest_missing',
                    'mismatched': [], 'missing': [], 'manifest': rel}
        stored = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(stored, dict):
            raise ValueError('manifest is not a {path: sha256} object')
        mismatched, missing = [], []
        for fpath, want in stored.items():
            got = _digest(str(fpath))
            if got is None:
                missing.append(str(fpath))
                continue
            if got != str(want):
                mismatched.append(str(fpath))
        ok = not mismatched and not missing
        out: Dict[str, Any] = {'ok': ok, 'mismatched': mismatched,
                               'missing': missing, 'manifest': rel}
        if not ok:
            out['reason'] = 'hash_mismatch' if mismatched else 'file_missing'
        return out
    except Exception as e:  # noqa: BLE001 — a broken manifest = not verified
        return {'ok': False, 'reason': f'manifest_unreadable: {type(e).__name__}',
                'mismatched': [], 'missing': [], 'manifest': rel}


_last_verify = 0.0
_VERIFY_INTERVAL_S = 30.0


def run_guard_tool(timeout_s: float = 60.0) -> Dict[str, Any]:
    """Execute qa's `python tests/core_guard.py` (the writer/verifier single
    source of truth — evolution/SEC-7 coordination). {ok, rc, detail}."""
    try:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / 'tests' / 'core_guard.py')],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout_s)
        return {'ok': proc.returncode == 0, 'rc': proc.returncode,
                'detail': ((proc.stderr or '') + (proc.stdout or ''))[-400:]}
    except Exception as e:  # noqa: BLE001 — infra failure = not verified
        return {'ok': False, 'rc': None,
                'detail': f'{type(e).__name__}: {e}'}


def check_at_boot() -> Dict[str, Any]:
    """[56] Fail-closed BEFORE serving: run qa's guard tool; drift or tool
    failure RAISES so uvicorn/TestClient never comes up (refuse to serve).
    Detailed verify() still feeds /status + SAFE_MODE bookkeeping."""
    global _boot_result, SAFE_MODE, _last_verify
    tool = run_guard_tool()
    res = verify()
    _boot_result = res
    _last_verify = time.monotonic()
    if not res.get('ok'):
        SAFE_MODE = {'active': True, **res}
    if not tool['ok'] or not res.get('ok'):
        try:
            from . import logjson
            logjson.slog('core_guard_refuse', tool_rc=tool.get('rc'),
                         reason=(res.get('reason') or tool.get('reason')
                                 or 'mismatch'),
                         mismatched=len(res.get('mismatched') or []),
                         missing=len(res.get('missing') or []))
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(
            'Core Guard verification failed — REFUSING TO SERVE '
            f'(tool_rc={tool.get("rc")}, reason={res.get("reason") or tool.get("detail")})')
    return res


def reverify_if_stale() -> Dict[str, Any]:
    """AUD-21 belt: periodic re-check (throttled) so a mid-run drift flips
    SAFE_MODE and blocks dispatch (status() refreshes it)."""
    global _boot_result, SAFE_MODE, _last_verify
    now = time.monotonic()
    if now - _last_verify < _VERIFY_INTERVAL_S and _boot_result is not None:
        return _boot_result or {}
    _last_verify = now
    res = verify()
    _boot_result = res
    if res.get('ok'):
        SAFE_MODE = {'active': False}
    elif not SAFE_MODE.get('active'):
        SAFE_MODE = {'active': True, **res}
        try:
            from . import logjson
            logjson.slog('core_guard_safe_mode', reason=res.get('reason'))
        except Exception:  # noqa: BLE001
            pass
    return res


def status() -> Dict[str, Any]:
    """Value-blind /status block (paths + counts only); refreshes the
    throttled re-verification (AUD-21) as a side effect."""
    try:
        reverify_if_stale()
    except Exception:  # noqa: BLE001
        pass
    res = _boot_result if _boot_result is not None else {'ok': None}
    out = {'active': bool(SAFE_MODE.get('active')), 'ok': res.get('ok'),
           'manifest': res.get('manifest')}
    if res.get('reason'):
        out['reason'] = res['reason']
    if res.get('mismatched'):
        out['mismatched'] = res['mismatched']
    if res.get('missing'):
        out['missing'] = res['missing']
    return out


def reset_for_tests() -> None:
    global _boot_result, SAFE_MODE, _last_verify
    _boot_result = None
    SAFE_MODE = {'active': False}
    _last_verify = 0.0
