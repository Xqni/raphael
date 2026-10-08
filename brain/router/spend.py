"""Persistent spend ledger for the user-approved vision-only paid slot (SEC-8).

Enforcement lives HERE, in code — never in agent honesty (AUDIT-2026-10-07,
SEC-8). Properties:

- **Append-only JSONL ledger** (`<repo_root>/run/vision_paid_ledger.jsonl`):
  one line per event (`call` / `alert` / `import`), so history survives
  restarts, partial writes, and code changes; nothing is ever rewritten.
- **Two ceilings:** per-day `providers.vision_paid_daily_cap_usd` (default
  $1.00) and an all-time `providers.vision_paid_total_cap_usd` (default
  $10.00). Either reached → callers get `RouterError(code="E_BUDGET")`.
- **Fail-closed on write failure:** if the ledger cannot be appended, the
  counter can no longer be trusted → `broken=True`, `exhausted` reads True,
  and the router refuses further paid calls (E_BUDGET / reason
  `ledger_unwritable`) instead of spending unaccounted money.
- **Conservative counting:** when the provider's usage response is malformed
  (no parseable cost AND no usable token counts), the call is charged the
  configured floor (`router.vision_paid_unknown_call_floor_usd`, default
  $0.005) — an unknown can only over-count, never under-count.
- **Legacy migration:** the pre-ledger `vision_paid_daily.json` state is
  imported once (then renamed `*.imported`) so live spend carries forward.

Cost basis (unchanged): provider-reported `cost` wins, else tokens ×
`router.vision_paid_price_per_mtok` (conservative sibling price, MODEL_POLICY).
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
DEFAULT_FLOOR_USD = 0.005          # charged when the usage response is garbage
LEDGER_FILENAME = "vision_paid_ledger.jsonl"
LEGACY_STATE_FILENAME = "vision_paid_daily.json"


# --------------------------------------------------------------------------- #
# cost estimation
# --------------------------------------------------------------------------- #
def estimate_cost_usd(
    usage: Mapping[str, Any] | None,
    price_per_mtok: Mapping[str, float] | None = None,
    reported_usd: float | None = None,
    floor_usd: float | None = None,
) -> float:
    """USD for one call: provider-reported cost → tokens × price → floor.

    `floor_usd` (SEC-8 "count conservatively") is returned when neither a
    usable reported cost nor usable token counts exist — callers pass the
    configured floor so a malformed usage response can never be counted as 0.
    """
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
    if in_tok == 0 and out_tok == 0:
        if floor_usd is not None:
            return round(float(floor_usd), 6)
        return 0.0
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


class SpendLedgerError(Exception):
    """Ledger append failed → the router must fail closed (refuse paid calls)."""


class DailySpend:
    """Daily + all-time USD ceilings backed by an append-only JSONL ledger."""

    def __init__(self, path: Path, cap_usd: float, *,
                 total_cap_usd: float | None = None,
                 floor_usd: float | None = DEFAULT_FLOOR_USD,
                 price_per_mtok: Mapping[str, float] | None = None) -> None:
        self.path = Path(path)
        if self.path.suffix == ".json":
            # legacy call sites passed the old state file → use the ledger name
            self.path = self.path.with_name(LEDGER_FILENAME)
        self.cap_usd = float(cap_usd)
        self.total_cap_usd = (None if total_cap_usd is None
                              else float(total_cap_usd))
        self.floor_usd = (None if floor_usd is None else float(floor_usd))
        self.price_per_mtok = dict(price_per_mtok or DEFAULT_PRICE_PER_MTOK)
        self._lock = threading.Lock()
        self.broken = False                # set when an append fails (fail-closed)
        self._today = self._today_str()
        self._today_usd = 0.0
        self._today_calls = 0
        self._total_usd = 0.0
        self._alerted_today = False
        self._import_legacy()
        self._load()

    # ------------------------------------------------------------------ #
    @staticmethod
    def _today_str() -> str:
        return date.today().isoformat()

    def _blank(self) -> None:
        self._today = self._today_str()
        self._today_usd = 0.0
        self._today_calls = 0
        self._alerted_today = False

    def _load(self) -> None:
        """(Re)build ALL in-memory totals from the append-only ledger.

        Always a full rebuild (file is the source of truth) — partial
        accumulation would double-count on every read.
        A malformed line is counted at the floor — history we cannot parse is
        spend we cannot prove was cheap (conservative, SEC-8)."""
        today = self._today_str()
        if today != self._today:
            self._blank()
        self._today = today
        self._today_usd = 0.0
        self._today_calls = 0
        self._alerted_today = False
        self._total_usd = 0.0
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                # unparsable fragment (crash mid-write) → charge the floor
                self._total_usd = round(self._total_usd + (self.floor_usd or 0.0), 6)
                continue
            if not isinstance(ev, dict):
                continue
            kind = ev.get("kind", "call")
            usd = 0.0
            try:
                usd = float(ev.get("usd") or 0.0)
            except (TypeError, ValueError):
                usd = self.floor_usd or 0.0
            self._total_usd = round(self._total_usd + usd, 6)
            if ev.get("date") == today:
                if kind == "call":
                    self._today_usd = round(self._today_usd + usd, 6)
                    self._today_calls += 1
                elif kind == "alert":
                    self._alerted_today = True

    def _append(self, entry: dict[str, Any]) -> None:
        """Append one line. ANY failure → SpendLedgerError (fail-closed)."""
        entry.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
        entry.setdefault("date", self._today_str())
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                fh.flush()
            self.broken = False
        except OSError as e:
            self.broken = True
            raise SpendLedgerError(
                f"vision spend ledger not writable: {self.path}") from e

    def _import_legacy(self) -> None:
        """One-time import of the pre-ledger run/vision_paid_daily.json state."""
        legacy = self.path.with_name(LEGACY_STATE_FILENAME)
        if not legacy.exists() or self.path.exists():
            return
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("usd"):
                self._append({"kind": "import", "date": str(data.get("date") or ""),
                              "usd": float(data.get("usd") or 0.0),
                              "model": "legacy-state"})
            legacy.rename(legacy.with_name(LEGACY_STATE_FILENAME + ".imported"))
        except (OSError, ValueError, TypeError):
            # never destroy the old state; it stays for manual reconciliation
            pass

    # ------------------------------------------------------------------ #
    # read side (thread-safe, allocation-cheap for /status polling)
    # ------------------------------------------------------------------ #
    @property
    def spent_usd(self) -> float:
        with self._lock:
            self._load()
            return self._today_usd

    @property
    def total_usd(self) -> float:
        with self._lock:
            self._load()
            return self._total_usd

    @property
    def calls(self) -> int:
        with self._lock:
            self._load()
            return self._today_calls

    @property
    def exhausted(self) -> bool:
        """Daily ceiling reached — or the ledger is unwritable (fail-closed)."""
        with self._lock:
            if self.broken:
                return True
            self._load()
            return self._today_usd >= self.cap_usd

    @property
    def total_exhausted(self) -> bool:
        with self._lock:
            if self.broken:
                return True
            self._load()
            if self.total_cap_usd is None:
                return False
            return self._total_usd >= self.total_cap_usd

    @property
    def alerted_today(self) -> bool:
        with self._lock:
            self._load()
            return self._alerted_today

    # ------------------------------------------------------------------ #
    # write side
    # ------------------------------------------------------------------ #
    def record(self, cost_usd: float, model: str = "") -> tuple[float, bool]:
        """Charge one call. Returns (today_total, crossed_a_ceiling).

        Raises SpendLedgerError when the line cannot be persisted — the
        caller MUST fail closed (refuse further paid calls) because the cap
        can no longer be enforced honestly.
        """
        with self._lock:
            self._load()
            before_day, before_total = self._today_usd, self._total_usd
            self._append({"kind": "call", "usd": round(max(0.0, float(cost_usd)), 6),
                          "model": str(model)[:120]})
            self._load()               # file is the source of truth
            crossed = (before_day < self.cap_usd <= self._today_usd)
            if self.total_cap_usd is not None:
                crossed = crossed or (before_total < self.total_cap_usd
                                      <= self._total_usd)
            return self._today_usd, crossed

    def mark_alerted(self) -> None:
        with self._lock:
            if self._alerted_today:
                return
            self._append({"kind": "alert", "usd": 0.0, "model": ""})
            self._alerted_today = True

    # ------------------------------------------------------------------ #
    def snapshot(self) -> dict[str, Any]:
        """State for /status + orb headroom (in-memory, no file re-read loop)."""
        with self._lock:
            self._load()
            return {
                "cap_usd": self.cap_usd,
                "spent_usd": self._today_usd,
                "calls": self._today_calls,
                "exhausted": self.broken or self._today_usd >= self.cap_usd,
                "total_cap_usd": self.total_cap_usd,
                "total_usd": self._total_usd,
                "total_exhausted": self.broken or (
                    self.total_cap_usd is not None
                    and self._total_usd >= self.total_cap_usd),
                "ledger_broken": self.broken,
                "ledger": str(self.path),
                "date": self._today_str(),
                "as_of": datetime.now().isoformat(timespec="seconds"),
            }
