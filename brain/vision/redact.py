"""Privacy redaction of screen-derived text (PROTOCOL §7 condition (3)).

`privacy.redact` lists what MUST be scrubbed from any extracted text before it
is spoken, journaled, or sent to a cloud model:
[api_key, token, password, card, email, phone].

Deterministic regex scrubbing — no model in the loop. Unknown kinds are
ignored (config may grow entries faster than patterns land). Applied to:
- vision answers (see_screen / computer-use observe),
- UIA element-tree text before it enters any cloud chat prompt.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Tuple

# (kind, compiled pattern, replacement) — order matters: specific before generic.
_RULES: Tuple[Tuple[str, "re.Pattern[str]", str], ...] = (
    # --- secrets -----------------------------------------------------------
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"), "[REDACTED:api_key]"),
    ("api_key", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{10,}\b"), "[REDACTED:api_key]"),
    ("api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{10,}\b"), "[REDACTED:api_key]"),
    ("api_key", re.compile(r"(?i)\bapi[\s_\-]?key\b(\s*[:=]\s*)(\S{4,})"),
     r"\1[REDACTED:api_key]"),
    ("token", re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\b"),
     "[REDACTED:token]"),
    ("token", re.compile(r"(?i)\b(token|bearer)\b(\s*[:=]\s*)(\S{4,})"),
     r"\1\2[REDACTED:token]"),
    ("password", re.compile(r"(?i)\b(pass(?:word|wd)?|pwd)\b(\s*[:=]\s*)(\S{3,})"),
     r"\1\2[REDACTED:password]"),
    # --- identifiers -------------------------------------------------------
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
     "[REDACTED:email]"),
    ("card", re.compile(r"\b(?:\d[ \-]?){13,19}\b"), "[REDACTED:card]"),
    # phone: 11-15 digits incl. separators (dates like 2026-10-05 = 8 digits — safe)
    ("phone", re.compile(r"(?<!\d)(?:\+?\d[\s().\-]*){10,14}\d(?!\d)"),
     "[REDACTED:phone]"),
)


def redact_text(text: str, kinds: Sequence[str]) -> str:
    """Scrub every configured kind from `text`. Returns `text` unchanged when
    there is nothing to do (or kinds is empty). Never raises on odd input."""
    if not text or not kinds:
        return text or ""
    wanted: List[str] = [str(k).strip().lower() for k in kinds if str(k).strip()]
    if not wanted:
        return text
    out = text
    for kind, pat, repl in _RULES:
        if kind in wanted:
            out = pat.sub(repl, out)
    return out


def available_kinds() -> Iterable[str]:
    return tuple(sorted({k for k, _, _ in _RULES}))
