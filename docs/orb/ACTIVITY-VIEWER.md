# F-3 — Activity viewer (DESIGN, reconciled to pc-control's schema)

**Status: design updated + implementation BLOCKED on brain-core's relay.**
No orb code.

## 0. Contract status (verify-first)

| Side | Evidence | State |
|---|---|---|
| pc-control — journal + inverse ops | `body/win/journal.py` + `body/win/tests/test_pc_journal.py` (their branch), spec in `docs/requests/pc-control__to__orb__activity-viewer-schema.md` | **ANSWERED** — their schema supersedes the one I proposed |
| pc-control — `activity` act | `body/win/actions.py:56` `PENDING_PROTO_ADDITIONS = ('activity',)` | **PENDING** protocol (`pc-control__to__integrator__protocol-activity-act.md`) |
| brain-core — relay endpoints | `brain/app.py:173-287` exposes only `/health`, `/jobs`, `/jobs/{id}`, `/jobs/{id}/cancel`, `/control`, `/status`, `/say` — `grep -n "activity" brain/app.py` → **ZERO HITS** | **BLOCKED** — `pc-control__to__brain-core__activity-endpoint.md` is still `Status: OPEN` |
| orb — viewer | this design | waiting |

My original proposal (`docs/requests/orb__to__pc-control__act-journal-schema.md`)
is now marked **ANSWERED** — pc-control owns the journal, so their field names
win. Differences adopted below: `seq` (not `id`) as the undo target, `kind` +
`inverse` instead of `reversible`/`undo`, and `POST /activity/undo {seq}` (not
`POST /activity/{id}/undo`).

---

## 1. Why an in-orb panel, not a native menu list

The packet says "viewer in menu area", honoured as **reached from the menu,
rendered as a panel**:

1. A native menu cannot scroll 30 rows or show a per-row result state.
2. Undo must be *verifiable* — the row has to flip to `Undone ✓` in front of the
   user; a menu closes on click and loses that.
3. The orb already has this pattern: `#typed`
   (`src/renderer/index.html`, W2.3 double-click → typed input →
   `command{source:'orb'}`). Reuse it instead of inventing a second overlay.

Entry point: `orbMenuTemplate()` (`src/main/main.js`) → `id: 'activity',
action: 'activity'` → opens the panel.

> **Open question for the integrator:** if "in menu area" is meant literally, say
> so and this becomes a native submenu instead. Everything below (data, rules,
> tests) is identical either way.

## 2. Entry schema — pc-control's, verbatim

```jsonc
{"seq": 42,                       // monotonic id — the undo TARGET
 "ts": 1791429000000,             // ms epoch, rendered relative ("2 min ago")
 "kind": "volume|brightness|window|recycle_move",
 "act": "volume",                 // act_req action that produced it
 "job": "j_20261007_0042",        // null for seeds/imports
 "summary": "volume 55 -> 42",    // pre-sanitised, safe to render
 "inverse": {...},                // OPAQUE — never rendered
 "undone": false,
 "undo_seq": 43}                  // present once undone
```

## 3. Viewer rules

```
┌──────────────────────────────────────────┐
│ Recent activity                        ✕ │
├──────────────────────────────────────────┤
│ 2 min ago   volume 55 -> 42      [Undo]  │  kind has an inverse, !undone
│ 9 min ago   brightness 80 -> 40    ·     │  undone already (or no inverse)
│ 14 min ago  window minimize        ·     │
│ 21 min ago  recycle_move           ·     │  RESERVED kind — never Undo
├──────────────────────────────────────────┤
│ Show more (20 of 128)                    │
└──────────────────────────────────────────┘
```

- **Newest-first** from `GET /activity?limit=20`; render `summary` + relative `ts`.
- **`[Undo]` only when `undone == false` AND `kind` has an inverse handler.**
  Today that whitelist is `volume | brightness | window`; `recycle_move` is
  **reserved — never render Undo for an unknown kind**. The whitelist lives in
  the viewer but is *derived from* pc-control's contract; if they add a kind, the
  panel silently shows no button (fail-closed) rather than a dead one.
- **Undo → `POST /activity/undo {"seq": n}`.** On **503 (Body offline)** show
  "Body offline" and leave the entry un-undone — **server state is truth**.
  One undo in flight at a time; a second click while pending is a no-op.
- After success the entry flips `undone: true`; update in place from the
  response's `{seq, kind, summary}` or re-fetch.
- **Never render `inverse` internals.** `summary` is pre-sanitised (no screen
  content, no paths) — the panel renders nothing beyond it (≤80 chars).
- States: loading = three skeleton lines (no spinner); empty = "No actions yet.";
  error = "Couldn't load activity (E_…)" + Retry. Never a blank panel.
- If the server returns `E_NOT_REVERSIBLE` for a row the panel thought was
  undoable, **drop the button and keep the row** — never retry.

## 4. Data + transport

| Need | Call |
|---|---|
| Fill the list | `GET /activity?limit=20` → `{ok, entries[]}` |
| Undo a row | `POST /activity/undo {"seq": n}` |

Same authenticated local REST pattern F-4 already ships (`main.js`
`refreshStatus()` reads `GET /status` this way): same port, same token,
`Authorization: Bearer`, TTL-coalesced, bounded read so a right-click never
stalls. **No new WS frames** — the orb is `role: ui` and may never emit `act_req`
(PROTOCOL §4); the Brain relays.

## 5. Test plan (mock-brain only — packet rule)

`body/orb/test/mock-brain.cjs` already serves `/status` with a 401-without-Bearer
rule; add `/activity` the same way, with fixtures covering: undoable-not-undone,
already-undone, reserved `recycle_move`, `ok:false`, and a `503` switch.

New phase `runActivity(cdp, brain, rec)` (`--only=activity`):

| check | proves |
|---|---|
| `activity_menu_item_present` | entry point exists in `orbMenuTemplate()` |
| `activity_panel_opens` | menu action → panel visible |
| `activity_rows_rendered_newest_first` | 5 rows, order correct |
| `activity_undo_only_for_undoable_kinds` | exactly the whitelist rows get `[Undo]` |
| `activity_undo_targets_seq` | POST body is `{seq: n}` |
| `activity_undo_marks_row` | flips to `Undone ✓`, button gone |
| `activity_undo_503_shows_body_offline` | entry stays un-undone (server truth) |
| `activity_never_renders_inverse` | raw `inverse` never reaches the DOM |
| `activity_degrades_honestly` | 503/no-data → error state, never blank |
| `activity_panel_never_changes_state` | `orb_state` untouched (same invariant as notices) |

Panel is **closed by default**, so it changes no pixel of the current sweep —
`distinctness` (104 pairs), `orb:size` and `orb:diff` stay valid.

## 6. Sequencing

1. ✅ design (this file) + schema agreement → pc-control answered.
2. ⛔ **brain-core**: `GET /activity` + `POST /activity/undo` — request OPEN,
   `brain/app.py` has no such route today.
3. ⏳ integrator: `activity` into PROTOCOL §7 (`PENDING_PROTO_ADDITIONS`).
4. ⏳ orb: menu item → panel → test phase → full gate.

**Nothing in step 4 starts before step 2 lands.**
