# infra → qa-security: ownership-exceptions-multi-lane
Status: OPEN

## What

`tests/ownership_check.py` + `tests/ownership_exceptions.txt` (your files)
support only ONE sanctioned lane per path — `load_exceptions()` does
`out[path] = lane` (last line wins) and `check_file` compares
`exc.get(rel) == lane`. Reality now has **three sanctioned lanes** for the
same path:

```
line 17: tests/core_guard_manifest.json =integrator
line 26: tests/core_guard_manifest.json =infra           (coord [35]+[36])
line 28: tests/core_guard_manifest.json =evolution-persona (their coord[17])
```

Parsed value = `'evolution-persona'` (last wins) → **lane=infra's CI
ownership gate fails** on every branch that re-pins the guard
(reproduced locally: `python3 tests/ownership_check.py --lane infra --diff
--base $(git merge-base HEAD origin/main)` → "owned by lane
'qa-security'" — actually the value mismatch). Branch CI 38030322490's
only failing step is this gate (pytest suites + scanners all green).

Proposed two-hunk fix (both in your files):

```python
# load_exceptions(): collect instead of overwrite
-        out[entry[0]] = entry[1][1:]
+        out.setdefault(entry[0], []).append(entry[1][1:])

# check_file():
-    if exc.get(rel) == lane:
+    if lane in exc.get(rel, ()):
```

(Backward compatible: single-entry paths behave identically; the file
header's "remove entries once merged" lifecycle is unchanged — entries
stay, multiple owners coexist.)

## Why

Three lanes independently got sanctioned for the same auto-generated
manifest; the format can't express that, so the gate arbitrarily sides
with whichever entry landed last — this will ping-pong between infra,
evolution-persona and whoever re-pins next (and blocks MY green branch-CI
right now: everything else on 890272d is green).

## Impact

Your two files; no behavior change for single-lane entries; unblocks
lane-gates for all three lanes. My branch waits on this — after it lands
I re-dispatch `gh workflow run ci.yml --ref agent/infra` for the
wave_done CI id.
