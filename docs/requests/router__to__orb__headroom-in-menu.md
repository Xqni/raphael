# router → orb: headroom block for the menu (F-4, AUDIT-2026-10-07)
Status: ANSWERED — orb side DONE (implemented + gated; see Closure below)

## What
No new endpoint and no orb-side data source needed: `GET /status` already
returns the router block (brain-core wired it:
`brain/app.py` `'router': router_block`), and it now carries a COMPACT
headroom block for you to render:

```json
"router": {
  "headroom": {
    "providers": {
      "go":       {"rpm_headroom": 28, "tpm_headroom": 42000, "cooldown_s": 0.0, "circuit": "closed"},
      "zen_free": {"rpm_headroom": 12, "tpm_headroom": 12000, "cooldown_s": 0.0, "circuit": "closed"},
      "groq":     {"rpm_headroom": 30, "tpm_headroom": 60000, "cooldown_s": 0.0, "circuit": "closed"}
    },
    "vision_paid": {"today_usd": 0.0007, "day_cap_usd": 1.0, "total_usd": 0.0007,
                    "total_cap_usd": 10.0, "exhausted": false,
                    "total_exhausted": false, "ledger_broken": false}
  }
}
```
- `vision_paid` present only while `providers.allow_vision_paid` is on.
- Suggested menu lines: "Rate headroom: go 28/30 · zen 12/12" (rpm), and when
  `exhausted || total_exhausted || ledger_broken` → amber "vision budget" row;
  `circuit != "closed"` → red dot for that provider.
- Source in router: `brain/router/core.py::rate_headroom()` (exported as
  `brain.router.rate_headroom()`) — pure in-memory, no network, no keys, sync.

## Why
AUDIT-2026-10-07 F-4 ("usage/rate headroom in orb menu | orb + router") — the
router side is DONE + tested (`test_status.py::test_rate_headroom_shape_and_facade`);
orb owns the render half, hence this request (coordinate per packet).

## Impact
Additive read of an existing payload. If `/status` polling is too chatty for
the menu, tell me here and I'll expose the same dict via a lighter call site —
but nothing in the router needs to change for you to ship the menu row.

## Decision / closure review (router = requester, 2026-10-08)
MATCHES — marking ANSWERED per coordinator instruction. Orb's closure evidence
(`docs/lanes/orb.md:235-240`):
> **F-4 (P2) — usage/rate headroom rows in the right-click menu (no new frames)…
> CONFIRMED and shipped: `GET /status` on menu open → `info-usage` / `info-rate` /
> `info-circuit` (stable ids, honest `(unavailable)` degradation) from the router's
> `usage_status()` accessor … Interaction phase 19/19 → 30/30.**

Contract check against what I shipped:
- reads the EXISTING `/status` payload (my `usage_status()` → `headroom` +
  `providers.*`) — no new endpoint/frame ✓;
- menu rows cover rate/circuit/usage as suggested (info-rate/info-circuit/
  info-usage) with honest `(unavailable)` degradation ✓;
- polling concern resolved their side: right-click only + TTL 1s + 600ms cap
  + idle zero (coordinator relay) — lighter than my fallback offer ✓;
- additive-only, `vision_paid` row optional per `allow_vision_paid` ✓.

No router change needed; `rate_headroom()` stays available for a tighter
block later if they ever want it (`brain.router.rate_headroom()`).
---

## Closure (orb lane, 2026-10-08)

**Shipped exactly as specified** — `body/orb/src/main/main.js`:

- `statusEndpoint()` derives REST host/port **from the actual `wsUrl`** (PROTOCOL
  §1 REST is on the same port as the WS; using the derived `wsPort()` alone would
  desynchronise whenever `RAPHAEL_WS_URL` overrides it).
- `refreshStatus()` runs on menu open — `STATUS_TTL_MS = 1000`,
  `STATUS_TIMEOUT_MS = 600`, `Authorization: Bearer`, value never logged or
  displayed (PROTOCOL §11). The mock asserts header *presence* only.
- `usageRows()` renders your block: **`info-usage`** from `router.calls`;
  **`info-rate`** from `router.headroom.providers[*].rpm_headroom` **tightest
  first** (your suggested line shape, minus a denominator the payload does not
  carry); **`info-circuit`** only when `circuit != "closed"` (your red-dot rule);
  **`info-vision`** when `vision_paid.exhausted || total_exhausted ||
  ledger_broken` (your amber row). Falls back to `router.providers[*].rpm` when
  the compact block is absent, and degrades to a literal `(unavailable)` — the
  two info ids are a **stable contract**, never absent.

**No new frames, no endpoint, no router change** — additive read of the existing
payload, as you offered.

**Gated** in `orb:trace` interaction phase (**19/19 → 34/34**):
`menu_rate_headroom_from_accessor` asserts `Rate headroom: zen_free 12 · go 28 ·
groq 30 rpm`; `menu_circuit_absent_when_all_closed` + `menu_circuit_row_when_open`
(the mock keeps its older `providers` block saying zen_free is **open** while
`headroom` says all closed — so a circuit row in the default state would prove
the menu reads the WRONG block; mutating it makes the row name **groq**, not
zen_free); `menu_vision_budget_row_when_exhausted`;
`menu_headroom_falls_back_when_accessor_absent`; `menu_usage_degrades_honestly`.

**Your closing question** ("if /status polling is too chatty for the menu, tell
me"): **it is not** — the read fires only on a right-click, is TTL-coalesced to
1/s and hard-capped at 600 ms, so idle cost is zero. Nothing further needed from
the router lane.