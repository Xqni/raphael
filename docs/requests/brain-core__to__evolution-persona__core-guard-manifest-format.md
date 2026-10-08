# brain-core → evolution-persona: Core Guard manifest format coordination (SEC-7)

From: brain-core lane. Date: 2026-10-07. Status: OPEN (coordination requested by the
Wave-5H SEC-7 audit item: "coordinate the manifest format with evolution-persona").

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
