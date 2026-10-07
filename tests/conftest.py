"""Path glue (integrator, 2026-10-05):
1) repo root on sys.path — tests import repo packages (`import body.win...`) as
   PEP 420 namespace packages, so the root must be importable no matter how
   pytest is invoked;
2) pin CWD to the repo root — conformance tests read repo files via
   CWD-relative paths (`Path("docs/PROTOCOL.md")`).
Both make `cd tests && ./.venv/bin/python -m pytest -q .` work as documented."""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if Path.cwd().resolve() != _ROOT:
    os.chdir(_ROOT)
