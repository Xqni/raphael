# F-3 — Activity viewer (DESIGN ONLY, Wave 5H)

**Status: design. Not implemented.** Blocked on the two upstream APIs named in
`docs/requests/orb__to__pc-control__act-journal-schema.md` (that file is the
schema agreement this design assumes). Implementation starts only after
pc-control exposes reversibility + undo, per the audit packet
`docs/audit-tasks/orb.md` (F-3, P2, CO-SHARE) and the user's "design first,
implement after pc-control exposes the API".

Mock-brain tests only (packet rule) — no live stack, no new dependency on a real
machine.

---

## 1. Why an in-orb panel, not a native menu list

The packet says "viewer in menu area". That is honoured as **reached from the
menu**, rendered as a panel, for three concrete reasons:

1. A native Electron menu cannot show a read-only *list* well — 20-30 rows in a
   submenu are unreadable, there is no scrolling, and each row needs its own
   "Undo" affordance plus a per-row result state (pending / done / failed).
2. Undo is a **state change the user must be able to verify**. A menu closes the
   moment you click; the "did it work?" feedback would be lost. The panel stays
   open and shows the row flipping to `Undone ✓`.
3. The orb already has this exact pattern: `#typed` (`src/renderer/index.html`,
   W2.3 double-click → typed input → `command{source:'orb'}`). The activity
   panel is the same mechanism with different content, so it inherits the
   existing show/hide, pointer and hit-testing behaviour instead of inventing a
   second one.

Entry point: a new menu item **`Activity…`** in `orbMenuTemplate()`
(`src/main/main.js`) → `id: 'activity', action: 'activity'` → opens the panel.

---

## 2. Panel anatomy

```
┌──────────────────────────────────────────┐
│ Recent activity                        ✕ │   header (read-only label)
├──────────────────────────────────────────┤
│ 18:15  Volume → 40            [Undo]     │   reversible + not yet undone
│ 18:14  Screenshot                    ·   │   read-only action: no button
│ 18:12  Volume → 25        [Undone ✓]     │   undo already applied
│ 18:10  Keystrokes: Ctrl+L           ·   │   irreversible: no button
│ 18:09  Open app: Firefox        [Undo]   │
├──────────────────────────────────────────┤
│ Show more (30 of 128)                    │   only when truncated
└──────────────────────────────────────────┘
```

- **Read-only list** of the most recent executed actions, newest first.
- One row = one journal entry (schema in the request file): `ts`, `summary`,
  `ok`, `reversible`, `undone`.
- **`[Undo]` appears only when `reversible === true && undone !== true`.**
  This is the whole safety story: a button that cannot do its job is never
  rendered. Irreversible and read-only actions get a `·` spacer so the column
  stays aligned and the *absence* of a button is visually deliberate.
- Rows with `ok === false` render the `error` code in a muted red and are still
  listed (an action that failed is exactly what a user wants to see).
- Empty / loading / error states:
  - loading → three skeleton lines (no spinner; the panel must not block input)
  - empty → "No actions yet."
  - error → "Couldn't load activity (E_…)" + a **Retry** control. Never blank.

## 3. Data + undo transport

Same shape as F-4 — authenticated local REST, **no new WS frames**:

| Need | Call |
|---|---|
| Fill the list | `GET /activity?limit=30` → `{ok, entries[]}` |
| Undo a row | `POST /activity/{id}/undo` → `{ok, entry}` or `{ok:false, code}` |

Read on open (TTL-coalesced like `refreshStatus()`, same 600 ms cap so a
right-click never feels stuck), then refresh only on explicit Retry or after a
successful undo.

**Undo flow:** click → row enters `pending` (button disabled, label
`Undoing…`) → POST → on success flip the row to `Undone ✓` and refresh; on
failure show the code inline (`E_NOT_REVERSIBLE`, `E_NOT_FOUND`, `E_BUSY`) and
re-enable the button if retryable. Exactly one undo in flight at a time — a
second click while pending is a no-op, not a queue.

**Fail-closed rules:**
- If `GET /activity` fails, show the error state. Never show a cached list as if
  it were live, and never show a row without its `id`.
- If the Brain responds `E_NOT_REVERSIBLE` for a row that claimed
  `reversible: true`, **remove the button and keep the row** (the server is the
  authority; the panel must not retry).

## 4. Privacy

- `args` in the journal is already a redacted SUMMARY (the `act_res` journal
  substitutes `"<omitted N b64 chars>"` for screenshot payloads —
  `brain/ws.py:671-680`). The panel additionally:
  - never renders anything longer than the server's `summary` (≤80 chars),
  - never renders raw `args`, only `summary`,
  - never renders `job` ids that are not already visible in the Jobs submenu,
  - shows **nothing** that is not in the response body — no local re-derivation,
    no screenshot thumbnails, no token/model material.
- Panel content is excluded from the frame trace the same way notices are
  (`traceRx` records the fact, never the payload beyond what the protocol
  already allows).

## 5. Test plan (mock-brain only)

`body/orb/test/mock-brain.cjs` gains an `/activity` fixture beside the `/status`
one added for F-4 (same 401-without-Bearer rule), with:
- 5 entries covering: reversible-not-undone, read-only, already-undone,
  irreversible, `ok:false` with an error code;
- a switch to serve `null` for the "Brain has no journal yet" path.

New phase `runActivity(cdp, brain, rec)` in `test/orb-trace.cjs`
(`--only=activity`), asserting:

| check | proves |
|---|---|
| `activity_menu_item_present` | the entry point exists in `orbMenuTemplate()` |
| `activity_panel_opens` | menu action → panel visible |
| `activity_rows_rendered` | 5 rows, newest first |
| `activity_undo_only_when_reversible` | **exactly** 1 `[Undo]` among the 5 |
| `activity_undo_reaches_brain` | POST hits the mock (transport, no new frame) |
| `activity_undo_marks_row` | row flips to `Undone ✓`, button gone |
| `activity_irreversible_error_shown` | `E_NOT_REVERSIBLE` rendered inline |
| `activity_degrades_honestly` | `null` fixture → error/empty state, never a blank panel |
| `activity_panel_never_changes_state` | `orb_state` untouched (same invariant as notices) |

Gate impact: the panel is **closed by default**, so it changes no pixel in the
existing sweep — `distinctness` (104 pairs), `orb:size` and `orb:diff` stay
valid without adjustment. If a future check opens the panel during a sweep, it
must be closed again before the sweep resumes.

## 6. Sequencing

1. **Now (done):** this design + the schema request to pc-control/brain-core.
2. **pc-control:** emit `reversible` / `undo` per executed action (it owns
   `body/win/actions.py`, the only place that knows).
3. **brain-core:** `GET /activity` + `POST /activity/{id}/undo`.
4. **orb:** menu item → panel → the test phase above → full gate
   (`test:unit`, `orb:trace`, `orb:size`, `orb:diff`).

No orb code lands before step 2 exposes its API.
