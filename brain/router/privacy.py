"""Privacy gates for every cloud call (PROTOCOL §7/§11, Wave 2 task 4).

Three hard gates live HERE, inside the router, so no caller can forget them:

1. **Private Mode** — `set_private_mode(True)` makes chat/vision/transcribe
   refuse (`RouterError(reason="private_mode")`). brain-core's control layer
   owns the flag (integrator, Core Guard); the router only honors it.
   Env escape hatch for tests/tools: `RAPHAEL_PRIVATE=1`.

2. **Foreground-window blocklist** — brain-core/pc-control registers a
   callable via `set_foreground_check(fn)`; when the focused window matches
   `privacy.blocklist_apps`, vision is refused outright and chat refuses too
   unless `router.block_chat_on_blocklist` is false (ARCHITECTURE §4:
   blocklist → local models only; under `cloud_temp` there are none, so the
   only safe action is refusal).

3. **Secret redaction before egress** — `redact_secrets()` replaces any
   loaded key value (from env or `.env`, presence-checked value-blind) plus
   generic credential patterns in every outbound message string.

Image bytes are never logged or persisted: `describe_image()` is the ONLY
image-related string this package ever produces (length + format).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]

_private = False
_foreground_check: Callable[[], "str | None"] | None = None
_secret_cache: tuple[float, dict[str, str]] | None = None  # (mtime, {name: value})


# --------------------------------------------------------------------------- #
# Private Mode / foreground hook
# --------------------------------------------------------------------------- #
def set_private_mode(value: bool) -> None:
    """Called by brain-core when `private_on`/`private_off` toggles."""
    global _private
    _private = bool(value)


def is_private_mode() -> bool:
    if os.environ.get("RAPHAEL_PRIVATE") in ("1", "true", "yes"):
        return True
    return _private


def set_foreground_check(fn: Callable[[], "str | None"] | None) -> None:
    """Register the foreground-window hook (brain-core/pc-control provides it).

    The callable returns the current foreground window/app name or None.
    It must be cheap and must never raise; the router guards it anyway.
    """
    global _foreground_check
    _foreground_check = fn


def foreground_window() -> str | None:
    if _foreground_check is None:
        return None
    try:
        return _foreground_check()
    except Exception:  # noqa: BLE001 — a broken hook must never crash a call
        return None


def blocklist_hit(blocklist_apps: Iterable[str]) -> str | None:
    """Matched blocklist entry for the focused window, or None."""
    name = foreground_window()
    if not name:
        return None
    low = name.lower()
    for app in blocklist_apps or ():
        if app and str(app).lower() in low:
            return str(app)
    return None


# --------------------------------------------------------------------------- #
# Secret discovery (value-blind: values are used only for substitution)
# --------------------------------------------------------------------------- #
_SECRET_ENV_NAMES = (
    "GROQ_API_KEY",
    "OPENCODE_API_KEY",
    "OPENCODE_ZEN_KEY",
    "ZEN_API_KEY",
    "GITHUB_TOKEN",
    "CIVITAI_TOKEN",
    "HF_TOKEN",
    "VAST_API_KEY",
    "RAPHAEL_TOKEN",
)


def _load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        if val:
            out[key.strip()] = val
    return out


def _dotenv_file() -> Path:
    env_path = os.environ.get("RAPHAEL_ENV_FILE")
    return Path(env_path) if env_path else REPO_ROOT / ".env"


def _secret_map() -> dict[str, str]:
    """{env_name: value} for every known secret — env wins over `.env`.

    Re-read `.env` only when its mtime changes (keys are injected at
    runtime). Values never leave this module except as redaction targets or
    an Authorization header built by a provider.
    """
    global _secret_cache
    out: dict[str, str] = {}
    for name in _SECRET_ENV_NAMES:
        val = os.environ.get(name)
        if val and len(val) >= 8:
            out[name] = val
    try:
        mtime = _dotenv_file().stat().st_mtime
    except OSError:
        mtime = 0.0
    cached_mtime, cached = _secret_cache if _secret_cache else (0.0, {})
    if mtime != cached_mtime:
        cached = _load_dotenv(_dotenv_file())
        _secret_cache = (mtime, cached)
    for name in _SECRET_ENV_NAMES:
        if name not in out:
            val = cached.get(name)
            if val and len(val) >= 8:
                out[name] = val
    return out


def secret(name: str) -> str | None:
    """Call-time value of one secret (env wins over `.env`) — never logged."""
    return _secret_map().get(name)


def secret_present(name: str) -> bool:
    """Value-blind presence check (AGENT_RULES §7)."""
    return bool(secret(name))


def secret_values() -> list[str]:
    """Loaded secret VALUES (env wins over .env), longest first.

    Only ever used to substitute them out of outbound text — never logged,
    never returned to callers, never written to disk.
    """
    values = list(_secret_map().values())
    # dedupe, longest first so substrings can't survive inside replacements
    return sorted(set(values), key=len, reverse=True)


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #
_REDACTED = "[REDACTED]"

# (pattern, replacement) — replacement is either REDACTED for the whole match
# or a callable keeping the pattern's group(1) prefix ("token=" stays, the
# value goes). Group(1) is ALWAYS the safe prefix when one is kept.
def _keep_prefix(m: re.Match[str]) -> str:
    return f"{m.group(1)}{_REDACTED}"


_GENERIC_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], Any], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}"), _REDACTED),
    (re.compile(r"\bgsk_[A-Za-z0-9_\-]{10,}"), _REDACTED),
    (re.compile(r"\bghp_[A-Za-z0-9_]{20,}"), _REDACTED),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), _REDACTED),
    (re.compile(r"\bhf_[A-Za-z0-9]{30,}"), _REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), _REDACTED),
    (re.compile(r"(?i)\b(authorization\s*[:=]\s*bearer\s+)[^\s'\"]+"), _keep_prefix),
    (re.compile(r"(?i)\b((?:api[_-]?key|apikey|access[_-]?key|client[_-]?secret|"
                r"token|password|passwd|secret)(?:\s*[=:]\s*))[^\s'\",;]+"),
     _keep_prefix),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?"
                r"-----END [A-Z ]*PRIVATE KEY-----"), _REDACTED),
)

_CARD_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<![\w.])\+?\d[\d \-()]{7,}\d(?![\w.])")


def _luhn_ok(candidate: str) -> bool:
    digits = [int(c) for c in candidate if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _scrub_card(match: re.Match[str]) -> str:
    return _REDACTED if _luhn_ok(match.group(0)) else match.group(0)


CATEGORY_PATTERNS: dict[str, tuple[tuple[re.Pattern[str], Any], ...]] = {
    "api_key": _GENERIC_SECRET_PATTERNS,
    "token": _GENERIC_SECRET_PATTERNS,
    "password": _GENERIC_SECRET_PATTERNS,
    "card": ((_CARD_RE, _scrub_card),),
    "email": ((_EMAIL_RE, _REDACTED),),
    "phone": ((_PHONE_RE, _REDACTED),),
}


def _apply(out: str, pairs: tuple[tuple[re.Pattern[str], Any], ...]) -> str:
    for pat, repl in pairs:
        out = pat.sub(repl, out)
    return out


def redact_secrets(text: str) -> str:
    """Replace loaded key values + generic credential patterns in `text`.

    Applied to EVERY outbound message string (chat/vision question/transcript
    guard). Never raises.
    """
    if not isinstance(text, str) or not text:
        return text
    try:
        out = text
        for val in secret_values():
            if val in out:
                out = out.replace(val, _REDACTED)
        out = _apply(out, _GENERIC_SECRET_PATTERNS)
        out = _CARD_RE.sub(_scrub_card, out)
        return out
    except Exception:  # noqa: BLE001 — redaction must never break a call
        return _REDACTED


def redact_categories(text: str, categories: Iterable[str]) -> str:
    """Config-driven redaction (`privacy.redact`) — used for text extracted
    from screenshots per PROTOCOL §7(3)."""
    if not isinstance(text, str) or not text:
        return text
    out = redact_secrets(text)
    for cat in categories or ():
        pairs = CATEGORY_PATTERNS.get(str(cat).lower())
        if pairs:
            out = _apply(out, pairs)
    return out


# categories that count as PERSONAL data for the free-model gate
# (allow_free_models_for_personal_data) — the PII trio from privacy.redact
PERSONAL_CATEGORIES: tuple[str, ...] = ("email", "phone", "card")


def detect_personal_data(messages: Any,
                         categories: Iterable[str] = PERSONAL_CATEGORIES) -> set[str]:
    """Which configured PII categories appear in the OUTBOUND content,
    checked BEFORE redaction (AUD-04). Walks strings the same way
    redact_messages does; never raises."""
    found: set[str] = set()
    cats = [str(c).lower() for c in categories or ()]
    if not cats:
        return found

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            for cat in cats:
                if cat in found:
                    continue
                for pat, _repl in CATEGORY_PATTERNS.get(cat, ()):
                    if pat.search(node):
                        found.add(cat)
                        break
        elif isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                _walk(value)

    _walk(messages)
    return found


def redact_messages(messages: Any, categories: Iterable[str] | None = None) -> Any:
    """Deep-copy OpenAI-style messages with every string redacted.

    `categories` = config `privacy.redact` (AUD-04: the CONFIGURED categories
    — email/phone/card/… — now apply to every outbound chat path; secrets are
    always scrubbed regardless)."""
    cats = tuple(str(c).lower() for c in categories or ())

    def _one(text: str) -> str:
        if cats:
            return redact_categories(text, cats)
        return redact_secrets(text)

    def _walk(node: Any) -> Any:
        if isinstance(node, str):
            return _one(node)
        if isinstance(node, list):
            return [_walk(m) for m in node]
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        return node

    return _walk(messages)


# --------------------------------------------------------------------------- #
# Image handling — metadata only, never the bytes
# --------------------------------------------------------------------------- #
def describe_image(image: Any) -> str:
    """The only image-related string the router ever logs (§7: no image logging)."""
    if isinstance(image, (bytes, bytearray)):
        return f"<image {len(image)} bytes>"
    if isinstance(image, (str, Path)):
        return f"<image path:{Path(image).name}>"
    return "<image>"
