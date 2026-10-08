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
import unicodedata
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
    there is nothing to do (or kinds is empty). Never raises on odd input.
    ALSO strips invisible/control characters (Wave 5H item 3: hidden-text
    injection fixtures must neutralize at the earliest chokepoint)."""
    if not text:
        return ""
    text = strip_invisible(text)
    if not kinds:
        return text
    wanted: List[str] = [str(k).strip().lower() for k in kinds if str(k).strip()]
    if not wanted:
        return text
    out = text
    for kind, pat, repl in _RULES:
        if kind in wanted:
            out = pat.sub(repl, out)
    return out


def strip_invisible(text: str) -> str:
    """Remove zero-width/format characters and control chars that hide text
    (U+200B..200D, U+FEFF, U+2060, C0/C1 controls) while KEEPING \\n/\\t
    (layout). Hidden payload = 'invisible instructions' has nowhere to hide."""
    if not text:
        return text or ""
    out = []
    for ch in text:
        if ch in "\n\t":
            out.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf"):
            continue            # control / format (zero-width, bidi, etc.)
        out.append(ch)
    return "".join(out)


def available_kinds() -> Iterable[str]:
    return tuple(sorted({k for k, _, _ in _RULES}))
