# F-3 — Activity viewer (DESIGN, aligned to the SIGNED schema agreement)

**Status: design current; implementation BLOCKED on brain-core's transport.**
No orb code. Packet `docs/audit-tasks/orb.md` (F-3, P2, CO-SHARE).

## 0. Which schema is authoritative (verify-first, 2026-10-08)

There are **two** pc-control specs in the tree and they disagree. Resolved:

| source | status | shape | verdict |
|---|---|---|---|
| `docs/requests/orb__to__pc-control__act-journal-schema.md` → `## Agreement (pc-control, 2026-10-08) — ACCEPTED with 3 corrections` | **DONE — AGREED** | my 12-field `id` / `reversible` / `undo` / `undo_ok` | **AUTHORITATIVE** |
| `docs/requests/pc-control__to__orb__activity-viewer-schema.md` | **OPEN** | earlier `seq` / `kind` / `inverse` / `undo_seq` | **SUPERSEDED** (flagged to pc-control — their file, not mine to edit) |

Why the agreement wins: it is marked `Status: DONE — AGREED`, it carries
pc-control's **3 corrections**, and it describes what they have actually
**shipped** — `body/win/journal.py log_entries()` returning *that* joined view,
plus tests named "orb field-exact log view" and "classification". An `OPEN`
proposal describing code that exists in a different shape cannot outrank a
`DONE` agreement describing code that exists.

**My earlier design had been reconciled to the superseded shape** (`seq` as
undo target, `kind`+`inverse`, `POST /activity/undo {seq}`). That is corrected
below.

## 1. Why an in-orb panel, not a native menu list

The packet says "viewer in menu area" — honoured as **reached from the menu,
rendered as a panel**:

1. A native menu cannot scroll 20–30 rows or show a per-row result state.
2. Undo must be *verifiable* — the row has to flip to `Undone ✓` in front of the
   user; a menu closes on click and loses that.
3. The orb already has this pattern: `#typed` (`src/renderer/index.html`, W2.3
   double-click → typed input → `command{source:'orb'}`). Reusing it means no
   second overlay mechanism to invent.

Entry point: `orbMenuTemplate()` (`src/main/main.js`) → `id: 'activity',
action: 'activity'` → opens the panel.

## 2. Entry schema — the AGREED shape

Served by `GET /activity?limit=20`, which Brain relays to the Body-side
`activity{op:"log", limit}` act (the two stores live on the Windows host, so
Brain asks the Body rather than reading files).

```jsonc
{"id": "a_1791463000123_00000007",  // stable: generated ONCE per dispatch,
                                     // STORED in both stores, never recomputed
 "ts": 1791463000123,                // ms epoch (rendered relative: "2 min ago")
 "job": "j_20261007_0042",           // null for seeds/imports
 "action": "volume",                 // a PROTOCOL §7 enum member
 "args": {"level": 42},              // summarize_args() output — redacted
 "ok": true,
 "error": null,
 "summary": "volume 55 -> 42",       // <= 80 chars, safe to render as-is
 "reversible": true,                 // pc-control's call, see §3
 "undo": {"action": "activity",
          "args": {"op": "undo", "seq": N}} | null,
 "undone": false,                    // true once an undo is APPLIED
 "undo_ok": null | true | false}     // false = undo refused, state UNCHANGED
```

- **Undo payload** is `activity{op:"undo"}` **by journal seq** — a normal §7
  `act_req`. Window-placement restores cannot be expressed as a raw
  `window{op}` replay, so the `activity` act is the universal executor.
- `POST /activity/{id}/undo` → Brain relays `activity{op:"undo", id}`;
  **Body resolves id → seq** (`id` and `seq` both accepted, `seq` XOR `id`).
- `args` is already a SUMMARY — the §7 action log stores `summarize_args()`
  (content keys length-only, b64 structural).

## 3. Reversibility — pc-control's corrected table

**Only four ever render an Undo.** Everything else silently renders no button —
the agreed wording being *"silence beats a lying button"*.

| action | reversible | undo |
|---|---|---|
| `volume`, `brightness` | **yes** | restore pre-action level (captured **before** the mutation) |
| `window` min/max/restore/**snap** | **yes** | restore full placement (rect + state) — **correction: `snap` added**; its rect is captured pre-change so it inverts exactly |
| `media` `play_pause`, `mute` | **yes** (toggles) | same-op replay (shipped) |
| `media` `next`/`prev`/`stop`/`vol_*` | **no** | no reliable prior state (`vol_*` would need a volume read the key path doesn't do) |
| `clipboard` write | **no for now** | their earlier "partial" was deferred (flavor-detection cost, low value); can flip later |
| `report` save | **no** | no `report{op:delete}` exists (confirmed) |
| `input`, `uia`, `launch_*`, `open_*`, `powershell`, `notify` | **no** | — |
| `screenshot`, `list_*`, `foreground_info` | n/a read-only | `reversible:false, undo:null` |
| `recycle_move` | reserved, no producer yet | — |

## 4. Viewer rules

- Newest-first from `GET /activity`; render `summary` + relative `ts`.
- **`[Undo]` only when `reversible === true && undone !== true`.** The whitelist
  in the viewer is *derived from* the table above — if pc-control adds a kind,
  the panel simply shows no button until the table is updated (fail-closed).
- **Undo → `POST /activity/{id}/undo`**, one in flight at a time (a second click
  while pending is a no-op, not a queue).
  - `200` → row flips to `Undone ✓` using the response's `{id, action, summary}`
    (or re-fetch).
  - `E_NOT_REVERSIBLE` → drop the button, **keep the row**; never retry (the
    server is the authority).
  - **`503` (Body offline) → show "Body offline" and leave the row
    un-undone** — server state is truth, and `undo_ok:false` means nothing
    changed.
- Loading = three skeleton lines; empty = "No actions yet."; error =
  "Couldn't load activity (E_…)" + Retry. **Never a blank panel.**
- **Never render `args` or any `undo` internals** — only the server's `summary`.

## 5. Transport — REST, no new frame (pc-control's correction #3)

| Need | Call |
|---|---|
| Fill the list | `GET /activity?limit=20` → `{ok, entries[]}` (relays `activity{op:"log",limit}`) |
| Undo a row | `POST /activity/{id}/undo` → `{ok, entry}` or `{ok:false, code}` (relays `activity{op:"undo", id}`) |

Accepted verbatim by pc-control; no `PROTOCOL.md` §3 edit, so the F-4 "no new
frames" rule stays respected. Same authenticated local-REST pattern F-4 already
ships (`main.js refreshStatus()`: same port, `Authorization: Bearer`,
TTL-coalesced, 600 ms cap).

## 6. Test plan (mock-brain only — packet rule)

`body/orb/test/mock-brain.cjs` gains `/activity` beside the `/status` fixture
(401 without Bearer), serving the agreed 12-field shape. Fixtures: reversible
not-undone, read-only, already-undone, irreversible, `ok:false`, plus a `503`
switch.

New phase `runActivity(cdp, brain, rec)` (`--only=activity`):

| check | proves |
|---|---|
| `activity_menu_item_present` | entry point exists in `orbMenuTemplate()` |
| `activity_panel_opens` | menu action → panel visible |
| `activity_rows_rendered_newest_first` | 5 rows, correct order |
| `activity_undo_only_when_reversible` | **exactly** the reversible rows get `[Undo]` |
| `activity_undo_targets_id` | POST body is `{id: …}` (agreed shape, not `{seq}`) |
| `activity_undo_marks_row` | flips to `Undone ✓`, button gone |
| `activity_undo_503_shows_body_offline` | row stays un-undone (server truth) |
| `activity_never_renders_args_or_undo_internals` | only `summary` reaches the DOM |
| `activity_degrades_honestly` | 503/no-data → error state, never blank |
| `activity_panel_never_changes_state` | `orb_state` untouched (same invariant as notices) |

Panel is **closed by default**, so it changes no pixel of the current sweep —
`distinctness` (104 pairs), `orb:size` and `orb:diff` stay valid.

## 7. Sequencing — what is actually blocking

| step | owner | state (verified 2026-10-08) |
|---|---|---|
| 1. schema agreement | orb + pc-control | ✅ **DONE** (`Status: DONE — AGREED`) |
| 2. journal + undo + `activity{op}` act | pc-control | ✅ **SHIPPED** (`journal.py`, `act_activity.py`, `act_system.py`, 7 tests) |
| 3. **protocol enum** | integrator | ⛔ `body/win/actions.py:56` still `PENDING_PROTO_ADDITIONS = ('activity',)` |
| 4. **`GET`/`POST /activity` relay** | brain-core | ⛔ `grep -c "'/activity" brain/app.py` → **0**; `pc-control__to__brain-core__activity-endpoint.md` = `Status: OPEN` |
| 5. orb panel + test phase | orb | ⏸ waiting on 3 + 4 |

**Nothing in step 5 starts before step 4 lands.** Steps 1–2 landing does not
unblock the render: the relay is the transport, and the enum is what lets Brain
legally send the act at all (PROTOCOL §7 is an allow-list).
