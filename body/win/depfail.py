"""SEC-9 (audit 2026-10-07): the Body NEVER installs packages at runtime.

Every former `_ensure_pkg` / pip fallback in body/win (audio_* excluded —
voice-owned) resolves to `require()`: `importlib.util.find_spec` ONLY — no
subprocess, no network, no pip. A missing dependency raises a RuntimeError
that names the package and points at the single pre-installed, hash-pinned
environment (`body/win/requirements.txt`, `--require-hashes`).
"""
import importlib.util

REQUIREMENTS = 'body/win/requirements.txt'
_HINT = ('install the pre-pinned environment: '
         'pip install --require-hashes -r %s' % REQUIREMENTS)


def require(dist: str, import_name: str = None) -> None:
    """Raise a clear, actionable error when a dependency is absent.

    dist        pip distribution name (what requirements.txt pins);
    import_name module to probe (defaults to dist; e.g. Pillow -> PIL).
    """
    module = import_name or dist
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        spec = None
    if spec is None:
        raise RuntimeError(
            "missing Body dependency '%s' — this build never pip-installs "
            'at runtime (SEC-9); %s' % (dist, _HINT))


def available(dist: str, import_name: str = None) -> bool:
    """True when the dependency is importable (tests/diagnostics)."""
    try:
        return importlib.util.find_spec(import_name or dist) is not None
    except (ImportError, ValueError):
        return False
