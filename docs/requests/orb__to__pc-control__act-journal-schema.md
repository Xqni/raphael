# orb → pc-control: act-journal schema for the activity viewer (F-3, Wave 5H)

Status: DONE — **AGREED by pc-control 2026-10-08** (see "## Agreement" below:
corrections to the table, wire shapes, and what shipped where). Orb may
implement the render against this shape; brain-core transport =
`pc-control__to__brain-core__activity-endpoint.md` (updated to op=log).

## Agreement (pc-control, 2026-10-08) — ACCEPTED with 3 corrections

**1. Entry shape: ACCEPTED as written** (all 12 fields), served by a NEW
`activity{op:"log", limit}` act (Body-side join — the two stores live on the
Windows host, so Brain must ask the Body, not read files):

```jsonc
{"id": "a_1791463000123_00000007",   // stable: generated ONCE per dispatch,
                                      // STORED in both stores, never recomputed
 "ts": …, "job": …, "action": …, "args": <redacted summary>, "ok": …,
 "error": …, "summary": "…<=80…",
 "reversible": true|false, "undo": {"action": "activity",
      "args": {"op": "undo", "seq": N}} | null,
 "undone": false, "undo_ok": null | true | false}
```

- `undo` payload: **`activity{op:undo}` by journal seq** (their §3 text said
  "Brain resolves entry.undo → issues a normal act_req" — this IS a normal
  §7 act_req; window-placement restores are not expressible as a raw
  `window{op}` replay, so the undo act is the universal executor).
- `POST /activity/{id}/undo` → Brain relays `activity{op:"undo", id}`
  (Body resolves id→seq; `id` accepted alongside `seq`).
- Args redaction: their requirement already holds — the §7 action log stores
  `summarize_args()` output (content keys length-only, b64 structural).

**2. Reversibility table: ACCEPTED with corrections** (mine = shipped):

| action | agreed reversible | undo |
|---|---|---|
| `volume`, `brightness` | **yes** | restore pre-action level (captured BEFORE mutation) |
| `window` min/max/restore/**snap** | **yes** | restore full placement (rect+state) — **CORRECTION: `snap` added** (their table put "move/resize = no"; snap's rect is captured pre-change so it inverts exactly) |
| `media` `play_pause`, `mute` | **yes** (toggles, per their default rule) | same op replay — **shipped**; `next`/`prev`/`stop`/`vol_*` = **no** (no reliable prior state; vol_* would need a volume read the key path doesn't do) |
| `clipboard` write | **no for now** (their "partial" deferred — flavor detection cost, low value; can flip later) |
| `report` save | **no** (no `report{op:delete}` exists — confirmed) |
| `input`, `uia`, `launch_*`, `open_*`, `powershell`, `notify` | **no** | matches their table |
| `screenshot`, `list_*`, `foreground_info` | n/a read-only | `reversible:false, undo:null` — matches |
| `recycle_move` | reserved in schema, no producer act yet | — |

Default rule honored: only volume/brightness/window/media-toggle are ever
`reversible:true`; everything else **silently renders no button** ("silence
beats a lying button" — agreed verbatim).

**3. Transport: REST ACCEPTED** — matches my brain-core request
(`GET /activity` relays `activity{op:"log",limit}`; `POST /activity/{id}/undo`
relays `activity{op:"undo",id}`); no §3 frame needed (my earlier
`activity` §7 act request already covers the act itself; F-4 "no new frames"
respected — the `foreground` frame was a separate granted need).

## What pc-control shipped (this branch)
- `body/win/actions.py` — stable `next_entry_id()` per dispatch, embedded in
  the §7 action log line (`id`) + the F-3 journal record.
- `body/win/journal.py` — `id`/`undo` payload on records, `ok:false` undo
  markers → `undo_ok:false` (state unchanged), `resolve_id`, `log_entries()`
  (the joined view above), `media` inverse.
- `body/win/act_activity.py` — `op: list|log|undo` (+ undo by `seq` XOR `id`).
- `body/win/act_system.py` — play_pause/mute journaled with inverse.
- Tests: id stability across restart, orb field-exact log view, classification
  (only the 4 safe kinds reversible), undo_ok failure path, media roundtrip.

## What

F-3 in `docs/audit-tasks/orb.md` is "CO-SHARE: activity-viewer render — agree
the act-journal schema with pc-control via `docs/requests`". This file is that
agreement. The orb cannot invent this: **only pc-control knows whether an
executed action can be undone**, and only it can perform the undo (the Body owns
the machine; the orb is `role: ui` and may never emit `act_req` — PROTOCOL §4).

### 1. Journal entry (one per *executed* action, i.e. one per `act_res`)

```jsonc
{
  "id": "a_20261007T181500_7f3a",  // stable + unique, safe to put in a URL
  "ts": 1791420900000,             // ms epoch when act_res ARRIVED
  "job": "j_ab12cd",               // owning job, or null for a detached act
  "action": "volume",              // exactly a PROTOCOL §7 enum member
  "args": { "level": 40 },         // args SUMMARY, already privacy.redact'd
  "ok": true,
  "error": null,                   // set when ok == false
  "summary": "Volume → 40",        // <= 80 chars, human-readable, no secrets
  "reversible": true,              // pc-control's call, see table below
  "undo": { "action": "volume", "args": { "level": 25 } },  // null if not
  "undone": false,                 // true once an undo has been APPLIED
  "undo_ok": null                  // null | true | false after an undo attempt
}
```

Constraints the orb will rely on (please keep):

- `id` must be **stable across restarts** (the viewer may reopen after an orb
  restart and must not offer an undo for an id it can no longer resolve).
- `args` is a SUMMARY. Screenshot bytes and any `privacy.redact` kind never
  appear here — the `act_res` journal already substitutes a
  `"<omitted N b64 chars>"` summary (`brain/ws.py:671-680`), same rule.
- Entries are **read-only** to the viewer. The orb never mutates the journal.

### 2. Reversibility — pc-control's classification

Only pc-control can answer this, so here is the proposal (a starting table,
please correct it rather than accept it):

| `action` | reversible? | proposed `undo` |
|---|---|---|
| `volume{level}` | **yes** | `volume` back to the pre-action level (pc-control captures it) |
| `brightness{level}` | **yes** | `brightness` back to the pre-action level |
| `media{op}` (play/pause/next) | **yes** for toggles | inverse `media` op; `next`/`prev` = not reversible |
| `clipboard{op}` set | **partial** | restore the prior TEXT only (image/any other flavor = no) |
| `window{op}` minimize/maximize | **yes** | inverse `window` op |
| `window{op}` close/move/resize | **no** | — |
| `input{keys\|mouse}` | **no** | keystrokes/clicks cannot be un-fired |
| `uia{op}` | **no** (default) | unless the specific op is a pure toggle pc-control can name |
| `launch_url`, `open_app`, `open_path` | **no** | — |
| `powershell{script_id,…}` | **no** | fixed registry, but the script's effects are opaque |
| `screenshot{}` | n/a | read-only — emit `reversible:false`, `undo:null` |
| `list_windows{}`, `foreground_info{}`, `list_running_apps{}` | n/a | read-only — no undo button at all |
| `report{op,…}` (save) | **partial** | `report{op:'delete'}` only if such an op exists; else no |
| `notify{text}` | **no** | — |

**Default rule if pc-control would rather not classify them all:** emit
`reversible:false, undo:null` for everything except the four clearly-safe rows
(`volume`, `brightness`, `media` toggles, `window` minimize/maximize). The
viewer shows no button when `reversible` is false — silence beats a lying button.

### 3. Transport — no new WS frames

The orb is `role: ui` and must not gain an `act_req` capability. Two REST calls
on the SAME port and token as everything else (PROTOCOL §2) cover it:

- `GET /activity?limit=30` → `{ "ok": true, "entries": [ journal entry… ] }`
  (Brain reads the journal; newest first; `limit` capped server-side)
- `POST /activity/{id}/undo` → `{ "ok": true, "entry": {…updated…} }` or
  `{ "ok": false, "code": "E_NOT_REVERSIBLE" | "E_NOT_FOUND" | "E_BUSY" }`
  (Brain resolves `entry.undo` → issues a normal `act_req` → Body executes;
  on success the entry's `undone` flips true and the result is re-readable
  from `GET /activity`)

Why REST and not a frame: it matches the F-4 "no new frames" rule, it needs no
`PROTOCOL.md` §3 edit, and the orb already proves it can do authenticated local
HTTP (F-4 reads `GET /status` the same way — `main.js` `refreshStatus()`).

Alternative if Brain-core prefers the WS: an additive `activity` frame pushed to
`ui` plus a `control{action:'undo'}` extension. Say which you want; the orb
implementation is one function either way.

## Why

- F-3 (P2, Wave 5H) is explicitly CO-SHARE and blocked on this agreement —
  "implement after pc-control exposes the API" (user).
- Reversibility is **semantic knowledge that lives only in `body/win/actions.py`**.
  Guessing it in the renderer would mean offering an Undo that silently does
  nothing, which is worse than offering none.
- The viewer must be read-only and mock-brain-testable; agreeing the shape here
  means the orb's tests can be written against a fixture before the real
  endpoints exist.

## Impact

- No `PROTOCOL.md` §3 change if REST is accepted (REST is already listed in §1).
- New Brain endpoint(s) — brain-core owns `brain/app.py`.
- New pc-control output: `reversible` / `undo` per executed action — pc-control
  owns `body/win/actions.py`.
- Orb: renderer + menu-area panel only, tested against mock-brain fixtures
  (`body/orb/test/mock-brain.cjs` already serves `GET /status`; it will serve
  `GET /activity` the same way).
