# infra → integrator: sec1-scrub-rehash
Status: APPROVED (approval source: coordinator scrub task, coord inbox ts
1791427356.186 — "SEC-1/ARCH-4 SCRUB TASK (wave-5H exit criterion 4): ...
scrub YOUR OWN files only ... Commit + CI id")

## What

Permission reference for a Core Guard manifest re-pin after the ORDERED
personal-data scrub of my own files:

- `python3 tests/core_guard.py --update --approval docs/requests/infra__to__integrator__sec1-scrub-rehash.md`

Files I changed that the guard pins (verified by `python3 tests/core_guard.py`
drift output — exactly these two, nothing else pinned):
1. `supervisor/main.py` — scrubbed: identity-fallback LOGIN literal →
   `LOGNAME`/`wsl-user` loud placeholder (config.yaml stays authoritative
   per your `_normalize` glue fix), integrator comment's win-login literal →
   `-u <win-user>` (comment text only).
2. `brain/raphael-brain.service` — `User`/`WorkingDirectory`/`PATH`/
   `ExecStart` → `<wsl-user>`/`<repo-root>` placeholders; header now points
   at `scripts/install-brain-unit.sh` (its sed rewrites all four lines
   regardless of placeholder content — sanity greps unchanged).

Unpinned files also scrubbed (no rehash needed): `docs/status/infra.md`
(evidence quotes redacted), `scripts/wslg-shadow/{boot-hook.sh,README.md}`,
`supervisor/tests/test_relay_bind.py` (fixture IP → stub), plus scanner
rule corrections (4-octet private IPs; bare `Zira` dropped — MS product
voice, not an anime clip).

## Why

Exit criterion 4 (zero personal data in tracked files) was assigned to this
lane; Core Guard (AGENT_RULES §8) pins `supervisor/**` + the unit, so the
scrub necessarily drifts them. The re-pin is the documented workflow
(`tests/core_guard.py --help`: "…ONLY legitimate with an integrator-approved
request in docs/requests/" — this file).

## Impact

Manifest hash entries for exactly the two files above; NO guard rule,
allow-list, or verifier logic changes (`--update` rewrites hashes only —
the commit shows the full manifest diff for review). If review finds the
diff touching anything beyond those two entries, revert this commit.
