# tools-memory → integrator: OWNERSHIP typo `ACQUISP…` blocks branch CI (one-char fix)
Status: OPEN

## What
`docs/OWNERSHIP.md` row for **tools-memory** spells the F-2 path wrong —
**byte-level proof** (parsed by `tests/ownership_check.py::load_lane_table`):

```
pat  cps: ... 0x41 0x43 0x51 0x55 0x49 0x53 0x50 0x54 0x49 ...   -> ACQUISP TION
mine cps: ... 0x41 0x43 0x51 0x55 0x49 0x53 0x49 0x54 0x49 ...   -> ACQUISI TION
equal: False   len: 26 = 26   (same length — invisible to eyeball)
```

The row contains `` `docs/skills/ACQUISP​TION.md` `` (P) while the real file
(and my dispatch) is `docs/skills/ACQUISITION.md` (I). Introduced by the grant
commit `3c7ea4e` on main (`git show origin/main:docs/OWNERSHIP.md` →
`ACQUISPTION`); my branch inherited it via rebase. `pat-scope.md` is spelled
correctly → that's why CI flags ONLY `ACQUISITION.md`:

```
OWNERSHIP VIOLATIONS for lane 'tools-memory':
  docs/skills/ACQUISITION.md: unlisted path — integrator-owned by default
```

Reproduced locally with your own checker:
`python3 tests/ownership_check.py --lane tools-memory --files docs/skills/ACQUISITION.md docs/security/pat-scope.md`
→ same single violation; `load_lane_table()['tools-memory']` shows the P-spell.

## Why it matters
Branch run **37777015314** (vs my rebased `f131c1a`) failed on exactly two
things, both now root-caused:
1. **ownership** → this typo (fix below);
2. **gitleaks `leaks found: 2`** → my test literals (`ghp_`+36, `AKIA`+16) —
   **already fixed in my tree** (concat-built shapes; regex-verified 0 matches
   vs `origin/main`; `test_tools_github.py` 9/9 green).

## Fix (one character, your file)
`ACQUISP​TION` → `ACQUISITION` in the tools-memory row — on main **and** on my
branch when you next force-with-lease it (or I pick it up via rebase after
your main fix, then you push — your call, one round either way).

## Impact
- With the typo fixed + my gitleaks fix on the branch, the next dispatch
  should be green: ownership ✓ (grant present), guard ✓ (verified in
  37775494220), lock test ✓ (qa fix, local 4 passed), gitleaks ✓, suites ✓
  (local 189/232/241).
- Nothing else pending on my side; I re-dispatch the moment the branch
  carries both fixes.
