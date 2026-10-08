"""Value-blind structured JSON logging (ARCH-6, CO-SHARE).

One JSON object per line: {"ts", "event", **fields}. EVERY string value is
redacted through `privacy.redact` (api_key/token/password/card/email/phone)
before serialization — if the redactor is unavailable the value is DROPPED
(value-blind by default, never fail-open). Keys are code constants chosen by
callers; secrets are never passed as keys (AGENT_RULES §7: presence only)."""
import json
import time
from typing import Any

from . import config as appcfg


def _kinds():
    try:
        return [str(k) for k in (appcfg.cfg_get(appcfg.get_config(),
                                                'privacy.redact', []) or [])]
    except Exception:  # noqa: BLE001 — default set if config unavailable
        return ['api_key', 'token', 'password', 'card', 'email', 'phone']


def redact_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        from brain.vision.redact import redact_text
        return redact_text(value, _kinds())
    except Exception:  # noqa: BLE001 — value-blind default: drop the value
        return '<redacted-unavailable>'


def slog(event: str, **fields: Any) -> str:
    """Structured, redacted log line (never raises, never prints secrets)."""
    try:
        safe = {str(k): redact_value(v) for k, v in fields.items()}
        line = json.dumps({'ts': int(time.time() * 1000),
                           'event': str(event), **safe},
                          ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        line = json.dumps({'ts': int(time.time() * 1000),
                           'event': str(event), 'log_error': True})
    print(line, flush=True)
    return line
