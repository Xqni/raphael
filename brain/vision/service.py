"""see_screen — screenshot via Body -> gates -> router.vision -> concise answer.

PROTOCOL §7 pipeline (this is the ONLY sanctioned cloud-egress path for screen
pixels; temporary for profile cloud_temp, removed at the Wave 6 cutover):

  private mode → profile legality → foreground blocklist → capture (downscale
  requested) → downscale verification → vision → redact answer.

Invariants enforced here (AGENT_RULES §7/§9 + lane task list):
- image bytes are NEVER written to disk, logs, events, or exceptions — the
  only use of `data` is passing it to the vision seam;
- everything read from the screen (including the model's answer) is untrusted
  data — returned as a string for the loop to wrap;
- every refusal is a SHORT speakable explanation, never a crash.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable, Optional

from .config import VisionConfig, load_config
from .gate import CloudVisionGate, Decision
from .seams import maybe_await_offloop

_MAX_ANSWER_CHARS = 700


class GateRefused(Exception):
    """A PROTOCOL §7 gate denied the capture. `reason` is speakable."""

    def __init__(self, decision: Decision):
        super().__init__(decision.reason or "screen access refused")
        self.code = decision.code
        self.reason = decision.reason or "Screen access refused."


@lru_cache(maxsize=1)
def default_config() -> VisionConfig:
    return load_config()


def default_is_private() -> bool:
    """Private Mode flag (brain/mode.py — integrator-owned Core Guard state)."""
    from brain.mode import get_mode
    return bool(get_mode().private)


async def capture_screen(gateway: Any, gate: CloudVisionGate,
                         config: Optional[VisionConfig] = None) -> bytes:
    """fg blocklist check -> capture -> downscale verify. Raises GateRefused.

    Order note: the foreground check runs BEFORE the capture so a blocked
    window is never even captured locally (the brief's screenshot→blocklist
    order is preserved functionally — blocklist still gates every send).
    Bug F: a probe FAILURE (body unreachable) raises GateRefused with the
    E_UNREACHABLE verdict — it is never collapsed into the privacy verdict
    (check_foreground(None)).
    `gateway` seam: `foreground_window() -> str|None`, `screenshot(max_px,
    quality) -> bytes` (both async; a returned None = unverifiable = closed).
    """
    cfg = config or gate.config
    try:
        title = await gateway.foreground_window()
    except Exception as e:       # noqa: BLE001 — unreachable != unverifiable
        raise GateRefused(gate.unreachable(CloudVisionGate.err_hint(e))) from None
    decision = gate.check_foreground(title)
    if not decision.ok:
        raise GateRefused(decision)
    try:
        data = await gateway.screenshot(cfg.max_px, cfg.quality)
    except Exception as e:       # noqa: BLE001 — speakable, never leaks bytes
        raise GateRefused(Decision.deny("E_CAPTURE", f"I couldn't capture the screen: {type(e).__name__}.")) from None
    decision = gate.check_image(data)
    if not decision.ok:
        raise GateRefused(decision)
    return data


async def see_screen(question: str, *, gateway: Any,
                     config: Optional[VisionConfig] = None,
                     gate: Optional[CloudVisionGate] = None,
                     vision_fn: Optional[Callable[..., Any]] = None,
                     is_private: Optional[Callable[[], bool]] = None) -> str:
    """Answer a question about the current screen. Always returns a string
    (the vision answer or a short refusal) — never raises for expected cases."""
    cfg = config or default_config()
    g = gate or CloudVisionGate(cfg)
    private = is_private if is_private is not None else default_is_private

    q = " ".join(str(question or "").split())
    if not q:
        return "Ask me something about the screen and I'll take a look."

    # 1. Private Mode: NO capture, NO model call (fastpath only).
    try:
        decision = g.check_private(bool(private()))
    except Exception:            # noqa: BLE001 — mode state unreadable = closed
        decision = g.check_private(True)
    if not decision.ok:
        return decision.reason

    # 2. profile legality (cloud ONLY under cloud_temp).
    decision = g.check_profile()
    if not decision.ok:
        return decision.reason

    # 3-5. blocklist + capture + downscale verification.
    try:
        data = await capture_screen(gateway, g, cfg)
    except GateRefused as ref:
        return ref.reason

    # 6. cloud vision (seam per INTERFACES §a) — never logged, never persisted.
    prompt = f"{q}\nAnswer briefly, in one or two sentences."
    try:
        fn = vision_fn
        if fn is None:
            from brain.router import vision as fn   # lazy (router lane seam)
        res = await maybe_await_offloop(fn, data, prompt, purpose="vision")
    except ImportError:
        return "Vision is unavailable right now (E_OFFLINE)."
    except Exception as e:       # noqa: BLE001 — RouterError etc. -> spoken code
        code = getattr(e, "code", None)
        if not isinstance(code, str) or not code.startswith("E_"):
            code = "E_OFFLINE"
        return f"Vision is unavailable right now ({code})."

    # 7. redact extracted text before it is spoken/journaled/re-prompted.
    if isinstance(res, dict):
        text = res.get("text")
    else:
        text = res
    text = g.redact(str(text or "").strip())
    if not text:
        return "I couldn't make out anything on that screen."
    if len(text) > _MAX_ANSWER_CHARS:
        cut = text[:_MAX_ANSWER_CHARS]
        text = cut.rsplit(" ", 1)[0].rstrip() + "…"
    return text
