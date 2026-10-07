"""JSON repair for tool-call arguments (Wave 2 task 2).

Providers return `function.arguments` as a STRING that is occasionally not
valid JSON: markdown fences, trailing commas, single quotes, unquoted keys,
or a truncated body (max_tokens cut mid-object). Consumers get a real dict —
repair happens once, at normalization, so no lane ever re-parses raw junk.
"""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*([\s\S]*?)\s*```\s*$", re.IGNORECASE)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.match(text)
    if m:
        return m.group(1).strip()
    # unterminated fence (truncated stream): drop the opener, keep the body
    if text.lstrip().startswith("```"):
        body = re.sub(r"^\s*```[a-zA-Z]*\s*", "", text, count=1)
        return body.replace("```", "").strip()
    return text.strip()


def _strip_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)


def _quote_keys(text: str) -> str:
    """`{name: "x"}` -> `{"name": "x"}` (unquoted / single-quoted keys only)."""
    return re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_\-]*)(\s*:)", r'\1"\2"\3', text)


def _single_to_double(text: str) -> str:
    """Convert single-quoted JSON-ish strings to double quotes."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    quote = ""
    while i < n:
        ch = text[i]
        if in_str:
            if ch == "\\" and i + 1 < n:
                out.append(text[i:i + 2])
                i += 2
                continue
            if ch == quote:
                out.append('"')
                in_str = False
                i += 1
                continue
            if ch == '"' and quote == "'":
                out.append('\\"')  # escape embedded double quote
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if ch in ("'", '"'):
            in_str = True
            quote = ch
            out.append('"' if ch == "'" else ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    if in_str and quote:
        out.append('"')  # close unterminated string
    return "".join(out)


def _balance(text: str) -> str:
    """Close unterminated objects/arrays/strings (truncated generation)."""
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
    out = text
    if in_str:
        out += '"'
    out += "".join(reversed(stack))
    return out


def repair_json(raw: Any) -> Any | None:
    """Best-effort parse of provider tool arguments.

    Returns the parsed object (dict/list/scalar) or None when nothing
    sensible can be recovered. Never raises.
    """
    if isinstance(raw, (dict, list)):
        return raw
    if raw is None:
        return None
    if isinstance(raw, (int, float, bool)):
        return raw
    if not isinstance(raw, str):
        raw = str(raw)
    text = _strip_fences(raw)
    if not text:
        return None

    attempts = [
        text,
        _strip_trailing_commas(text),
        _quote_keys(_strip_trailing_commas(text)),
        _single_to_double(_quote_keys(_strip_trailing_commas(text))),
        _balance(_single_to_double(_quote_keys(_strip_trailing_commas(text)))),
    ]
    seen: set[str] = set()
    for cand in attempts:
        if cand in seen:
            continue
        seen.add(cand)
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def repair_arguments(raw: Any) -> tuple[dict[str, Any], bool]:
    """Normalize tool arguments to a dict.

    Returns `(arguments_dict, repaired)` where `repaired` is True when the
    provider's payload was malformed and we had to (or had to try to) fix it.
    Unrecoverable payloads keep the original text under `_raw` so nothing is
    silently lost — `repaired` is then True and callers can log a warning.
    """
    if isinstance(raw, dict):
        return dict(raw), False
    if raw is None:
        return {}, False
    parsed = repair_json(raw)
    if isinstance(parsed, dict):
        original_is_valid = isinstance(raw, str) and _is_valid_json(raw)
        return parsed, not original_is_valid
    if isinstance(parsed, list):
        return {"items": parsed}, True
    if isinstance(raw, str) and raw.strip():
        return {"_raw": raw}, True
    return {}, False


def _is_valid_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, ValueError):
        return False
