"""Analysis-mode context gathering (Wave 5 lane task) — screen + foreground +
window history for deep-dive requests, with redaction discipline applied to
every payload that will reach a model (analysis or simulation purposes).

Shapes: PROTOCOL §7 read-only actions only (`foreground_info`, `list_windows`,
`screenshot` — all lock:false), all gates reused from the vision gate:
Private Mode (no probes at all), profile legality, debug_capture, foreground
blocklist (also FILTERED from window lists/history — window titles of
sensitive apps never reach a cloud model), image verification, redaction.

Window history is an in-process ring buffer: every foreground probe the
production gateway makes records `(ts, identity)` here — never disk, never
logged; blocklist entries are filtered at EMIT time (local memory may hold
them; models never see them).
"""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

from .config import VisionConfig
from .gate import PASSWORD_FOCUS_REASON, CloudVisionGate
from .seams import maybe_await_offloop

_MAX_HISTORY = 32                 # stored entries (ring)
_HISTORY_EMIT = 12                # entries in a context payload
_MAX_WINDOWS = 10                 # window rows in a context payload
_MAX_CHARS = 3000                 # total payload bound (words cut at the end)

_history: Deque[Tuple[float, str]] = deque(maxlen=_MAX_HISTORY)


def record_foreground(identity: Optional[str]) -> None:
    """Record one foreground observation (production gateway calls this on
    every successful probe). Consecutive duplicates collapse; None ignored."""
    if not identity:
        return
    ident = " ".join(str(identity).split())
    if not ident:
        return
    if _history and _history[-1][1] == ident:
        _history[-1] = (time.time(), ident)   # refresh ts, no duplicate row
        return
    _history.append((time.time(), ident))


def recent_history(limit: int = _HISTORY_EMIT) -> List[Tuple[float, str]]:
    return list(_history)[-limit:]


def reset_history() -> None:
    """Tests only (name is the convention signal)."""
    _history.clear()


def _blocked(gate: CloudVisionGate, identity: Optional[str]) -> bool:
    return gate.matched_blocklist_app(identity) is not None


def _line(ident: str) -> str:
    return ident if len(ident) <= 120 else ident[:117] + "..."


async def gather_context(
        *,
        question: str = "",
        include_screen: bool = True,
        include_windows: bool = True,
        include_history: bool = True,
        gateway: Any,
        gate: CloudVisionGate,
        config: Optional[VisionConfig] = None,
        vision_fn: Optional[Any] = None,
        is_private: Optional[Any] = None) -> str:
    """Compose the context block (redacted, bounded, never private)."""
    cfg = config or gate.config
    q = " ".join(str(question or "").split())
    try:
        private = bool(is_private()) if is_private is not None else False
    except Exception:            # noqa: BLE001 — unreadable mode = closed
        private = True
    if private:
        return ("Context unavailable: private mode is on "
                "(no screen or window data is read).")

    sections: List[str] = []

    # ---- foreground (one probe; unreachable = nothing else to trust) --------
    try:
        fg = await gateway.foreground_window()
    except Exception as e:       # noqa: BLE001 — availability, not privacy
        return "Context unavailable: " + gate.unreachable(
            CloudVisionGate.err_hint(e)).reason
    if fg:
        record_foreground(fg)
    # Wave 5H item 2: focused password field -> no context at all.
    if getattr(gateway, "password_focus", False):
        return "Context withheld: " + PASSWORD_FOCUS_REASON
    if fg is None:
        sections.append("Foreground: unknown (could not be verified)")
    elif _blocked(gate, fg):
        # identity withheld from the MODEL (blocklist); local speech may name it
        sections.append("Foreground: a sensitive app is in front "
                        "(identity withheld, screen capture refused)")
    else:
        sections.append(f"Foreground: {_line(str(fg))}")

    # ---- current windows (list_windows, filtered + bounded) ----------------
    if include_windows:
        try:
            res = await gateway.list_windows()
        except Exception as e:   # noqa: BLE001
            res = e
        if isinstance(res, Exception):
            sections.append("Windows: unavailable (%s)"
                            % CloudVisionGate.err_hint(res))
        elif isinstance(res, dict):
            rows: List[str] = []
            entries = res.get("windows") or []
            for w in entries:
                if not isinstance(w, dict):
                    continue
                title = " ".join(str(w.get("title") or "").split())
                proc = " ".join(str(w.get("process") or "").split())
                ident = " | ".join(x for x in (title, proc) if x)
                if not ident or _blocked(gate, ident):
                    continue    # sensitive titles never reach the model
                mark = "  [foreground]" if w.get("foreground") else ""
                rows.append(_line(ident) + mark)
                if len(rows) >= _MAX_WINDOWS:
                    break
            more = len([w for w in entries if isinstance(w, dict)]) - len(rows)
            head = "Windows (open, foreground first):"
            if rows:
                sections.append(head + "\n" + "\n".join("  - " + r
                                                         for r in rows)
                                + ("\n  … and %d more" % more if more > 0
                                   else ""))
            else:
                sections.append(head + " none shareable")
        else:
            sections.append("Windows: unavailable (unexpected reply)")

    # ---- recent foreground history (local ring, filtered) -------------------
    if include_history:
        rows = []
        for ts, ident in recent_history():
            if _blocked(gate, ident):
                continue
            stamp = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            rows.append("%s  %s" % (stamp, _line(ident)))
        if rows:
            sections.append("Recent foreground window history:\n"
                            + "\n".join("  - " + r for r in rows))
        else:
            sections.append("Recent foreground window history: (none yet)")

    # ---- optional gated screen description ---------------------------------
    if include_screen:
        if fg is None or _blocked(gate, fg):
            # NEVER echo the gate reason here: it names the app, and this
            # payload goes TO the model (see_screen's spoken wording is
            # user-facing; this is cloud-bound text).
            sections.append("Screen: withheld — the foreground window is "
                            "sensitive or could not be verified")
        elif not gate.check_profile().ok:
            sections.append("Screen: " + gate.check_profile().reason)
        elif not gate.check_debug_capture().ok:
            sections.append("Screen: " + gate.check_debug_capture().reason)
        else:
            try:
                data = await gateway.screenshot(cfg.max_px, cfg.quality)
            except Exception as e:  # noqa: BLE001
                sections.append("Screen: " + gate.unreachable(
                    CloudVisionGate.err_hint(e)).reason)
            else:
                decision = gate.check_image(data)
                if not decision.ok:
                    sections.append("Screen: " + decision.reason)
                else:
                    prompt = (q or "Describe the screen") + \
                        ("\nDescribe briefly what is visible: window, key "
                         "controls, text. One or two sentences.")
                    try:
                        res = await maybe_await_offloop(
                            vision_fn, data, prompt, purpose="vision")
                    except Exception as e:   # noqa: BLE001
                        code = getattr(e, "code", None)
                        code = code if isinstance(code, str) and \
                            code.startswith("E_") else "E_OFFLINE"
                        sections.append(
                            f"Screen: vision unavailable ({code}).")
                    else:
                        desc = str((res or {}).get("text")
                                   if isinstance(res, dict) else (res or ""))
                        desc = " ".join(desc.split())
                        sections.append(
                            "Screen: " + (desc or "(no description)"))

    out = "\n".join(sections)
    out = gate.redact(out)                 # redaction discipline (§7(3))
    if len(out) > _MAX_CHARS:
        out = out[:_MAX_CHARS].rsplit("\n", 1)[0] + "\n…"
    return out
