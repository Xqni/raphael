"""Shared token helpers (REST + WS hub use the same source of truth).
RAPHAEL_TOKEN_PATH lets tests point at a temp file so the REAL ~/.raphael/token
is never written or deleted (tests/test_health.py keeps that fixture pattern).
"""
import hmac
import os


def get_token():
    path = os.environ.get('RAPHAEL_TOKEN_PATH') or os.path.expanduser('~/.raphael/token')
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
