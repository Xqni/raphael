"""Daily USD spend accounting for the user-approved vision-only paid slot.

Scope: `providers.allow_vision_paid` (config.yaml, USER APPROVAL 2026-10-06,
logged in docs/PAID_USAGE.md) — ONE Go-tier vision model, `vision()` purpose
only, hard daily stop at `providers.vision_paid_daily_cap_usd` (default 1.00).

Cost basis (no pricing endpoint exists for the runtime):
1. if the provider response carries an actual cost (`cost` / `usage.cost`),
   that wins — it is the provider's own number;
2. otherwise estimate from token usage × `router.vision_paid_price_per_mtok`
   (USD per 1M in/out). The default is the NEAREST LISTED SIBLING price from
   docs/MODEL_POLICY.md (`deepseek-v4-pro` 0.66/1.98) — deliberately
   conservative for the unlisted `…deepseek-v4-flash-vision-exp`, so the cap
   trips EARLY and a single call can overshoot by at most one call's cost.

State lives in `<repo_root>/run/vision_paid_daily.json` (gitignored runtime
data; resets when the local date rolls over). Tests point repo_root at tmp_path.
"""
from __future__ import annotations

import json
import subprocess
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

# conservative upper bound for the unlisted vision model — see module docstring
DEFAULT_PRICE_PER_MTOK: dict[str, float] = {"input": 0.66, "output": 1.98}


def estimate_cost_usd(
    usage: Mapping[str, Any] | None,
    price_per_mtok: Mapping[str, float] | None = None,
    reported_usd: float | None = None,
) -> float:
    """USD for one call: provider-reported cost wins, else tokens × price."""
    if reported_usd is not None:
        try:
            value = float(reported_usd)
            if value >= 0:
                return round(value, 6)
        except (TypeError, ValueError):
            pass
    usage = usage or {}
    price = dict(DEFAULT_PRICE_PER_MTOK)
    if price_per_mtok:
        price.update({k: float(v) for k, v in price_per_mtok.items()})
    try:
        in_tok = max(0, int(usage.get("input") or 0))
        out_tok = max(0, int(usage.get("output") or 0))
    except (TypeError, ValueError):
        in_tok = out_tok = 0
    usd = (in_tok * price.get("input", 0.0) + out_tok * price.get("output", 0.0)) / 1_000_000
    return round(usd, 6)


def notify_attention(text: str) -> None:
    """Record an item for the human + notify (coord `attention`).

    Never raises and never blocks a call: the coord CLI may be absent (tests,
    bare checkout) or the platform may refuse the toast — the spend cap itself
    is already enforced by DailySpend either way.
    """
    try:
        coord = Path.home() / ".raphael-coord" / "bin" / "coord"
        if not coord.exists():
            return
        subprocess.run([str(coord), "attention", str(text)],
                       timeout=10, capture_output=True, check=False)
    except Exception:  # noqa: BLE001 — notification is best-effort
        pass


class DailySpend:
    """Thread-safe daily USD counter with a hard cap (hard stop, not a target)."""

    def __init__(self, path: Path, cap_usd: float) -> None:
        self.path = Path(path)
        self.cap_usd = float(cap_usd)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    @staticmethod
    def _today() -> str:
        return date.today().isoformat()

    def _blank(self) -> dict[str, Any]:
        return {"date": self._today(), "usd": 0.0, "calls": 0,
                "alerted": False, "models": []}

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._blank()
        if not isinstance(data, dict) or data.get("date") != self._today():
            return self._blank()          # date rolled over → fresh budget
        return data

    def _save(self, data: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass  # accounting must never break a vision call

    # ------------------------------------------------------------------ #
    @property
    def spent_usd(self) -> float:
        with self._lock:
            return float(self._load().get("usd") or 0.0)

    @property
    def calls(self) -> int:
        with self._lock:
            return int(self._load().get("calls") or 0)

    @property
    def exhausted(self) -> bool:
        """True once today's recorded spend has reached the cap (hard stop)."""
        with self._lock:
            return float(self._load().get("usd") or 0.0) >= self.cap_usd

    @property
    def alerted_today(self) -> bool:
        with self._lock:
            return bool(self._load().get("alerted"))

    def record(self, cost_usd: float, model: str = "") -> tuple[float, bool]:
        """Add one call's cost. Returns (new_total, just_crossed_the_cap)."""
        with self._lock:
            data = self._load()
            before = float(data.get("usd") or 0.0)
            total = round(before + max(0.0, float(cost_usd)), 6)
            data["usd"] = total
            data["calls"] = int(data.get("calls") or 0) + 1
            if model and model not in data.get("models", []):
                data.setdefault("models", []).append(model)
            crossed = before < self.cap_usd <= total
            self._save(data)
            return total, crossed

    def mark_alerted(self) -> None:
        with self._lock:
            data = self._load()
            data["alerted"] = True
            self._save(data)

    def snapshot(self) -> dict[str, Any]:
        """State for health()/status consumers (no file writes)."""
        with self._lock:
            data = self._load()
        return {
            "cap_usd": self.cap_usd,
            "spent_usd": float(data.get("usd") or 0.0),
            "calls": int(data.get("calls") or 0),
            "exhausted": float(data.get("usd") or 0.0) >= self.cap_usd,
            "date": data.get("date"),
            "as_of": datetime.now().isoformat(timespec="seconds"),
        }
