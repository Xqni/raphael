"""Wave 5U Wave A — chat/UI tripwires (qa-security §5.5 task 8).

Gates (static, over the orb renderer + WS URL derivation — all landed now):
1. NO innerHTML sinks fed by frames in the orb/chat UI (XSS via a malicious
   job/subtitle frame). Static grep over body/orb/src: no innerHTML,
   outerHTML, insertAdjacentHTML, or document.write. [LANDED]
2. Token NEVER appears in a URL or a log line. The WS URL is derived without
   the token (token is sent in the auth message, never in the query string),
   and the token is never console.logged. [LANDED]
3. `chat` role cannot send act_res/audio — pinned in the background gates file
   (test_wave5u_background_gates) against brain/ws.py CAN_SEND sets.

The Raphael Chat web page itself (a separate chat UI with its own DOM sinks +
CSP) is orb's Wave B; the renderer-wide innerHTML ban + token hygiene apply to
everything shipped today and are the substrate the chat page must inherit.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ORB_SRC = REPO / "body" / "orb" / "src"

# files under orb/src that are actual shipped JS/HTML (skip node_modules)
def _shipped_files():
    out = []
    for p in ORB_SRC.rglob("*"):
        if "node_modules" in p.parts or not p.is_file():
            continue
        if p.suffix in {".js", ".html", ".mjs"}:
            out.append(p)
    return out


def test_no_innerhtml_sinks_in_orb_renderer():
    """XSS guard: no HTML-injection sinks fed by data frames anywhere in the
    shipped orb/chat renderer. Any innerHTML/outerHTML/insertAdjacentHTML/
    document.write redden the suite."""
    sinks = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write")
    offenders = []
    for f in _shipped_files():
        # comment-aware (integrator transitional fix 2026-10-10, credited qa):
        # the naive substring scan flagged orb's OWN guard comment ("never
        # innerHTML") in renderer.js. Strip //, /* */ and # comment lines —
        # real sinks (assignments/calls) still redden the suite.
        code_lines = []
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.lstrip()
            if s.startswith(("//", "/*", "*", "#")):
                continue
            code_lines.append(line)
        text = "\n".join(code_lines)
        for s in sinks:
            if s in text:
                offenders.append(f"{f.relative_to(REPO)}: {s}")
    assert not offenders, f"HTML-injection sinks in orb renderer: {offenders}"


def test_ws_url_never_carries_the_token():
    """Token hygiene: the derived WS URL must not embed the token (it travels
    in the auth message). instance.js must never build a ws:// URL with a
    token= query — checked across the whole module, not just wsUrl()."""
    inst = (ORB_SRC / "main" / "instance.js").read_text(encoding="utf-8")
    assert re.search(r"function wsUrl\(\)", inst), "wsUrl() not found"
    # no ws:// or wss:// URL anywhere may carry a token= query
    assert not re.search(r"wss?://[^'\"`]*token", inst, re.I), \
        "a ws:// URL embeds the token"
    # wsUrl() specifically must not reference the token at all
    fn = re.search(r"function wsUrl\(\)[\s\S]*?\n\}", inst)
    body = fn.group(0) if fn else ""
    assert "token" not in body.lower(), "wsUrl() references the token"


def test_token_is_never_logged():
    """Token hygiene: no console/log call may pass the token."""
    offenders = []
    for f in _shipped_files():
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
                r"(console\.(log|info|debug|warn|error)|logger\.\w+)\([^)]*token",
                text, re.I):
            offenders.append(f"{f.relative_to(REPO)}: {m.group(0)[:60]}")
    assert not offenders, f"token in a log call: {offenders}"
