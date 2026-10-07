"""BodyGateway — the act pipeline (PROTOCOL §7) used by see_screen and the
computer-use loop.

Must run ON the brain's main loop: `hub.broadcast` only schedules work when a
loop is running in the current thread, and `engine.expect_act` futures must be
awaited on the loop where `_on_act_res` delivers them. Sync tool entrypoints
reach this via wiring.run_sync (asyncio.run_coroutine_threadsafe).

Seam contract consumed here (mocked in tests until pc-control lands):
  window{op:"foreground"}            -> {title, process}     (request file
                                    docs/requests/computer-use__to__pc-control__
                                    screen-context-ops.md)
  screenshot{max_px, quality}        -> {b64, bytes}
  uia{op:"tree", target, args}       -> {text}

Read-only calls (screenshot/foreground/uia tree) are sent lock:false — they
never touch mouse/keyboard. Acting calls are sent lock:true so the Body's own
last-line arbitration applies (the brain-level lock is held by the job via
needs_lock=True metadata).
"""
from __future__ import annotations

import base64
import uuid
from typing import Any, Dict, Optional


class ActError(Exception):
    """Structured act-pipeline failure (PROTOCOL §10 code when available)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code if isinstance(code, str) and code.startswith("E_") else "E_INTERNAL"
        self.detail = str(detail or code)


class BodyGateway:
    def __init__(self, hub: Any = None, engine: Any = None, timeout: float = 30.0):
        self._hub = hub
        self._engine = engine
        self.timeout = float(timeout)

    # ---- lazy wiring -------------------------------------------------------
    @property
    def hub(self) -> Any:
        if self._hub is None:
            from brain.ws import get_hub
            self._hub = get_hub()
        return self._hub

    @property
    def engine(self) -> Any:
        if self._engine is None:
            from brain.jobs.engine import get_engine
            self._engine = get_engine()
        return self._engine

    # ---- act pipeline ------------------------------------------------------
    def _ref(self, ref: Optional[str]) -> str:
        if ref:
            return str(ref)
        # Journal linkage: use the current lock-owning job when there is one
        # (computer_use holds it), else an opaque per-call ref.
        owner = getattr(self.engine.lock, "owner", None)
        if owner is not None:
            try:
                from brain.jobs import store
                return store.job_ext_id(owner)
            except Exception:    # noqa: BLE001 — journal linkage is best-effort
                pass
        return f"cap_{uuid.uuid4().hex[:12]}"

    async def act(self, action: str, args: Optional[Dict[str, Any]] = None,
                  *, lock: bool = False, ref: Optional[str] = None,
                  timeout: Optional[float] = None) -> Any:
        """Send one act_req and await the body's act_res. Returns `result`
        on ok, raises ActError otherwise. Never raises raw provider junk."""
        hub = self.hub
        engine = self.engine
        if hub.get_body_session() is None:
            raise ActError("E_INTERNAL", "no body session connected")
        ref = self._ref(ref)
        fut = engine.expect_act(ref)
        hub.broadcast({
            "type": "act_req", "v": 1, "job": ref,
            "action": action, "args": args or {},
            "lock": bool(lock),
            "timeout_ms": int((timeout or self.timeout) * 1000),
        }, roles={"body"})
        res = await engine.await_act_res(fut, ref, timeout=timeout or self.timeout)
        if not isinstance(res, dict) or not res.get("ok"):
            err = (res or {}).get("error") if isinstance(res, dict) else "E_ACT_TIMEOUT"
            err = err or "E_ACT_TIMEOUT"
            raise ActError(str(err), str(err))
        return res.get("result")

    # ---- typed helpers -----------------------------------------------------
    async def screenshot(self, max_px: int, quality: int) -> bytes:
        result = await self.act("screenshot",
                                {"max_px": int(max_px), "quality": int(quality)},
                                lock=False)
        raw: Any = None
        if isinstance(result, dict):
            raw = result.get("b64")
        elif isinstance(result, str):
            raw = result
        if not raw:
            raise ActError("E_INTERNAL", "screenshot result had no image data")
        try:
            data = base64.b64decode(raw, validate=False)
        except Exception as e:   # noqa: BLE001
            raise ActError("E_INTERNAL", f"screenshot decode failed: {type(e).__name__}") from None
        if not data:
            raise ActError("E_INTERNAL", "empty screenshot")
        return data

    async def foreground_window(self) -> Optional[str]:
        """Window title of the foreground window; None = unverifiable
        (the gate fails closed on None)."""
        result = await self.act("window", {"op": "foreground"}, lock=False)
        if isinstance(result, dict):
            if "title" in result:
                title = result.get("title")
                return str(title) if title is not None else None
            return None
        if isinstance(result, str):
            return result
        return None

    async def uia_tree(self, max_chars: int = 4000, max_depth: int = 12) -> str:
        result = await self.act("uia", {
            "op": "tree",
            "target": {"scope": "foreground"},
            "args": {"max_chars": int(max_chars), "max_depth": int(max_depth)},
        }, lock=False)
        if isinstance(result, dict):
            text = result.get("text")
            return str(text or "")
        if isinstance(result, str):
            return result
        return ""

    async def run_action(self, name: str, args: Dict[str, Any], *,
                         lock: bool, ref: Optional[str] = None) -> Any:
        """Dispatch a validated computer-use action (input-touching = lock)."""
        return await self.act(name, args, lock=lock, ref=ref)
