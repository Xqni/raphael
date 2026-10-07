"""BodyGateway — the act pipeline (PROTOCOL §7) used by see_screen and the
computer-use loop.

Must run ON the brain's main loop: `hub.broadcast` only schedules work when a
loop is running in the current thread, and `engine.expect_act` futures must be
awaited on the loop where `_on_act_res` delivers them. Sync tool entrypoints
reach this via wiring.run_sync (asyncio.run_coroutine_threadsafe).

Seam contract (PROTOCOL §7 as amended 2026-10-06; shipped by pc-control in
body/win/act_window.py + act_uia.py — my request
…__pc-control__screen-context-ops.md was superseded by their landing):
  foreground_info{}                  -> {'window': {title, process, pid, ...}
                                             | None}   (None = unverifiable)
  uia{op:"tree", element:{control_type:"window"},
      args:{depth, timeout_s}}       -> structured element tree (dict) —
                                             rendered to TEXT here (lane rule:
                                             UIA tree arrives as text)
  screenshot{max_px, quality}        -> {'b64', 'bytes'}

Read-only calls (screenshot/foreground_info/uia tree) are sent lock:false —
they never touch mouse/keyboard. Acting calls are sent lock:true so the Body's
own last-line arbitration applies (the brain-level lock is held by the job via
needs_lock=True metadata).
"""
from __future__ import annotations

import base64
import uuid
from typing import Any, Dict, Optional

_TREE_DEPTH = 2          # body range 1..3 (root + 2 levels is plenty for observe)
_TREE_TIMEOUT_S = 1.0    # body range 0.5..15; fg window matches immediately
_DEFAULT_MAX_CHARS = 4000


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
        # (computer_use holds it), else an opaque per-call ref. Engine may be
        # a test double without a lock — duck-typed, never fatal.
        lock = getattr(self.engine, "lock", None)
        owner = getattr(lock, "owner", None) if lock is not None else None
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
        """Identity of the foreground window via PROTOCOL §7 `foreground_info{}`.

        Returns `"title | process"` (either may be absent), so the blocklist
        matches BOTH fields — title-only matching was bypassable (an untitled
        KeePass dialog titled 'Enter Master Key' has process 'KeePass.exe').
        None = unverifiable (no window, wrong shape, or a real window with
        ZERO identity) — the gate fails closed on None.
        """
        result = await self.act("foreground_info", {}, lock=False)
        if isinstance(result, dict):
            win = result.get("window")
            if not isinstance(win, dict):
                return None                      # {'window': None} / bad shape
            title = " ".join(str(win.get("title") or "").split())
            process = " ".join(str(win.get("process") or "").split())
            ident = " | ".join(x for x in (title, process) if x)
            if not ident:
                return None                 # real window, zero identity
            # Wave 5: every production probe feeds the local window-history
            # ring (in-memory only; filtered+redacted at emit — context.py).
            try:
                from brain.vision.context import record_foreground
                record_foreground(ident)
            except Exception:    # noqa: BLE001 — history must never break a probe
                pass
            return ident
        return None

    async def list_windows(self) -> Dict[str, Any]:
        """PROTOCOL §7 `list_windows{}` — read-only window enumeration for
        Analysis context (lock:false). Returns the body's dict as-is; callers
        filter blocklist entries before anything reaches a model."""
        result = await self.act("list_windows", {}, lock=False)
        if isinstance(result, dict):
            return result
        return {}

    async def uia_tree(self, max_chars: int = _DEFAULT_MAX_CHARS,
                       depth: int = _TREE_DEPTH,
                       timeout_s: float = _TREE_TIMEOUT_S) -> str:
        """Foreground window's UIA element tree AS TEXT (UIA-first observe).

        Selector: control_type=window with index 0 — the body scans the
        foreground window subtree first (winlayer._iter_candidates), so the
        first match is the foreground top-level window. The body returns a
        STRUCTURED tree; render_tree() turns it into bounded indented text.
        """
        depth = max(1, min(3, int(depth)))
        result = await self.act("uia", {
            "op": "tree",
            "element": {"control_type": "window"},
            "args": {"depth": depth, "timeout_s": float(timeout_s)},
        }, lock=False)
        return render_tree(result, max_chars=max_chars)

    async def run_action(self, name: str, args: Dict[str, Any], *,
                         lock: bool, ref: Optional[str] = None) -> Any:
        """Dispatch a validated computer-use action (input-touching = lock)."""
        return await self.act(name, args, lock=lock, ref=ref)


def render_tree(node: Any, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    """Body UIA tree dict -> bounded plain text for prompts (AGENT_RULES §9:
    this text is screen DATA and is wrapped as untrusted by the caller).

    Line shape: `<indent><control_type> "name" [automation_id]` — truncated
    with a marker at max_chars so a 500-node tree can never blow a prompt.
    """
    if not isinstance(node, dict):
        return ""
    lines = []
    used = 0

    def walk(n: Any, level: int) -> bool:
        """Returns True when the char budget is exhausted (stop)."""
        nonlocal used
        if not isinstance(n, dict):
            return False
        role = " ".join(str(n.get("control_type") or "?").split()) or "?"
        name = " ".join(str(n.get("name") or "").split())
        aid = " ".join(str(n.get("automation_id") or "").split())
        line = "%s%s \"%s\"" % ("  " * level, role, name)
        if aid:
            line += " [%s]" % aid
        if used + len(line) + 1 > max_chars:
            return True
        lines.append(line)
        used += len(line) + 1
        for child in (n.get("children") or []):
            if walk(child, level + 1):
                return True
        return False

    truncated = walk(node, 0)
    if truncated or node.get("truncated"):
        if used + 3 <= max_chars:
            lines.append("…")
    return "\n".join(lines)
