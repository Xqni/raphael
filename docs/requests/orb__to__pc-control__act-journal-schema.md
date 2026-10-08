# orb → pc-control: act-journal schema for the activity viewer (F-3, Wave 5H)

Status: OPEN
Asks: **pc-control** (action semantics + undo capability) and **brain-core**
(read model + undo transport). Orb implements the RENDER only, after both land.

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
