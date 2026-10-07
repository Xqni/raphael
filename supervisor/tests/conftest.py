"""Path glue + env hygiene for supervisor tests (infra lane).

Repo root on sys.path (import supervisor.*) and RAPHAEL_INSTANCE/PORT/
PROFILE/BIND scrubbed before every test so `main`-default assertions are
deterministic no matter what the invoking shell exported.
"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture(autouse=True)
def _clean_instance_env(monkeypatch):
    for var in ("RAPHAEL_INSTANCE", "RAPHAEL_PORT", "RAPHAEL_PROFILE",
                "RAPHAEL_BIND"):
        monkeypatch.delenv(var, raising=False)
