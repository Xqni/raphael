"""Shared token helpers (REST + WS hub use the same source of truth).
RAPHAEL_TOKEN_PATH lets tests point at a temp file so the REAL ~/.raphael/token
is never written or deleted (tests/test_health.py keeps that fixture pattern).
"""
import hmac
import os


def default_token_path():
    """Token path for the CURRENT instance (INTERFACES §d).

    RAPHAEL_TOKEN_PATH always wins. Unset instance (`main`) resolves to
    ~/.raphael/token — byte-for-byte the previous behavior. A lane instance
    resolves to ~/.raphael/<instance>/token so two stacks never share one
    credential (approved 2026-10-06: docs/requests/pc-control__to__integrator
    __instance-token-path.md; Body's token_candidates() already matches).
    """
    env = os.environ.get('RAPHAEL_TOKEN_PATH')
    if env:
        return env
    name = (os.environ.get('RAPHAEL_INSTANCE') or '').strip() or 'main'
    root = os.path.expanduser('~/.raphael')
    return os.path.join(root, 'token') if name == 'main' \
        else os.path.join(root, name, 'token')


def get_token():
    path = default_token_path()
    try:
        with open(path, 'r') as f:
            return f.read().strip() or None
    except OSError:
        return None


def check_token(candidate) -> bool:
    """Constant-time token compare (PROTOCOL §2). Denies when no token configured."""
    expected = get_token()
    if not expected or not candidate:
        return False
    return hmac.compare_digest(expected, str(candidate))


def bearer_from_header(authorization):
    if authorization and authorization.lower().startswith('bearer '):
        return authorization[7:].strip()
    return None
