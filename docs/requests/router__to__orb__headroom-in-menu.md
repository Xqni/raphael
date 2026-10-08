# router → orb: headroom block for the menu (F-4, AUDIT-2026-10-07)
Status: ANSWERED

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
