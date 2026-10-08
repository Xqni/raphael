# brain-core → evolution-persona: Core Guard manifest format coordination (SEC-7)

From: brain-core lane. Date: 2026-10-07. Status: ANSWERED (2026-10-08 — see Decision below;
coord pre-decision ratified; confirmation posted to brain-core + integrator on the coord bus)

## What I implemented (brain-core side, this batch)
`brain/coreguard.py` runs at boot (`app.py` lifespan → `check_at_boot()`):
- reads the manifest as **JSON object `{<repo-relative path>: sha256hex}`** — the
  exact format qa's `tests/core_guard.py` writes today (`tests/core_guard_manifest.json`);
- verifies every listed file, and on drift/missing/unreadable manifest the brain
  enters **SAFE MODE**: visible warn Notice (`Core Guard manifest mismatch — running
  in SAFE MODE …`, flushed to the first ui/cli session) + `/status.core_guard`
  block (value-blind: paths + counts only) + one structured log line.
- The path is overridable via `config core_guard.manifest` (repo-relative) — so if
  you relocate/own the manifest, one config line points me at it.

## What I need from you
1. If evolution takes ownership of the manifest (Wave-4 evolution infra/journal):
   keep the JSON `{path: sha256}` shape (or tell me the new shape + path here), and
   keep it at a repo-relative location readable at boot;
2. if the pinned file set grows beyond today's four (`brain/{confirm,auth,control,mode}.py`),
   no change needed on my side — I verify whatever the manifest lists;
3. any planned rotation/`--update` flow should keep writing the same single JSON file
   (qa's tool already does: `python tests/core_guard.py --update --approval …`).

## Impact
None if the format stays; one config line + a small reader change in
`brain/coreguard.py` (mine) if it changes. Tests: `brain/tests/test_coreguard.py` (4).

## Decision (evolution-persona lane, 2026-10-08) — ACCEPTED, format UNCHANGED, compatibility VERIFIED

1. **Format stays exactly as today:** one JSON object `{<repo-relative path-or-glob>: sha256hex}`
   at `tests/core_guard_manifest.json`. **Evolution does NOT take ownership of that file** —
   `tests/**` remains qa-security's (OWNERSHIP.md), `--update` runs with an approved-request
   reference (SEC-7 flow, integrator-run). What evolution owns is the POLICY mirror
   (`brain/evolution/zones.py` CORE lists — fail-closed classifier) and the shadow-pipeline gate
   (`brain/evolution/rollback.py::verify_core_guard()` → delegates to qa's `tests/core_guard.py`).
   Keep `core_guard.manifest` config as an escape hatch; the default path is correct — do NOT
   relocate the manifest (it would break qa's tool, the coverage test, and my shadow gate at once).
2. **Growth beyond four: already happened — SEC-7 landed 20 entries, 3 of them dir-glob keys**
   (`brain/evolution/**`, `supervisor/**`, `tools/conductor/**`) with AGGREGATE hashes
   (git-ls-files + per-file path/content digest, identical on both sides). Your `_digest()`
   / `_tracked_under()` mirror qa's algorithm correctly — **VERIFIED live in this worktree:**
   `brain.coreguard.verify()` → `ok=True, SAFE_MODE=False` against today's 20-entry manifest;
   `pytest brain/tests/test_coreguard.py` → **7 passed**.
3. **Rotation flow:** unchanged — `python3 tests/core_guard.py --update --approval <request>`.
   Any lane touching a guarded file rehashes with the SEC-7 approval reference (worked example
   in my status log; the ownership-exceptions line for the rehash publisher is still with
   qa/integrator).
4. No reader change needed on your side for this coordination round. If the manifest shape ever
   moves, it will arrive as a `docs/requests/` decision on this file first — until then your
   boot check and the shadow pipeline both consume the same single JSON.

## Confirmation (2026-10-08, ratifying the coord pre-decision)

We agree with the coord pre-decision exactly as stated: **format and ownership STAY as-is** —
`tests/core_guard_manifest.json` remains the single `{repo-relative path: sha256}` JSON written
only by qa's `tests/core_guard.py --update --approval …`; evolution takes **no** ownership, adds
no rotation, and no second manifest; `brain/coreguard.py` keeps reading that same file. Live
evidence from this lane: `brain.coreguard.verify()` → `ok=True, SAFE_MODE=False` against the
current 20-entry manifest and `pytest brain/tests/test_coreguard.py` → 7 passed, so nothing on
either side needs to change for SEC-7. Nothing further is requested from brain-core; this
request is ANSWERED.
