# brain-core → computer-use: test_hardening.py relative import breaks pytest collection on main

From: brain-core lane. Date: 2026-10-07. Status: DONE (fixed on main by
integrator commit c60c23c — sanctioned try/except pattern applied in the
merge window; independently re-verified by computer-use 2026-10-07: exact CI
step `pytest -q brain --collect-only` = 771 tests collected, 0 errors on
current origin/main rebase. No further action.)

## What
`brain/tools/computer_use/tests/test_hardening.py:11` does
```python
from .harness import (CHANGED_TREE, ...)
```
but `brain/tools/computer_use/tests/__init__.py` was **removed by qa-security** (commit
0e8310b — removing it fixed their registry-pollution double-import flake; please do NOT
restore it). Without a package marker, pytest's default (prepend) import mode loads the
file top-level → relative import fails:

```
$ python -m pytest -q brain
ERROR brain/tools/computer_use/tests/test_hardening.py
E   ImportError: attempted relative import with no known parent package
(741 tests collected, 1 error → collection INTERRUPTED)
```
This is exactly CI's full-brain step (`.github/workflows/ci.yml` line 78: `python -m pytest -q brain`)
→ main CI is red on this file. Your other two files already use the sanctioned pattern
(test_runner.py / test_see_screen.py, qa's 0e8310b).

## Fix (match the existing pattern)
```python
try:
    from .harness import (CHANGED_TREE, DEFAULT_TREE, ScriptedChat,
                          ScriptedGateway, final_reply, make_deps)
except ImportError:      # no package marker (qa 0e8310b) -> top-level import
    from harness import (CHANGED_TREE, DEFAULT_TREE, ScriptedChat,
                         ScriptedGateway, final_reply, make_deps)
```
(prepend mode inserts the tests/ dir on sys.path, so the bare `harness` import resolves.)

## Why me filing it
I run the full matrix per wave and hit it; the file is yours (brain/tools/computer_use/**).
Verified workaround on my branch: `pytest brain/tools/computer_use/tests --import-mode=importlib`
→ 60 passed, 2 skipped (their suite itself is green — only the import style breaks).
