"""Path glue for brain/tools/pc tests: repo root on sys.path so
`import brain.tools.pc` / `import body.win.*` work regardless of how pytest
is invoked (mirrors tests/conftest.py, scoped to this folder)."""
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
