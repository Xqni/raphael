"""conftest for body/win tests (pc-control lane).

Gives pytest the repo root (namespace packages `body.win.*`), and provides:
  fake      — a FakeWin bound as the OS backend (reset afterwards)
  actlog    — action log redirected to tmp (never writes repo logs/)
  instance  — RAPHAEL_INSTANCE=pc-control for isolation tests
NEVER registers hotkeys, opens the mic, or injects real input (AGENT_RULES §5).
"""
import os
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from body.win import winlayer  # noqa: E402
from body.win.fakewin import FakeWin  # noqa: E402


@pytest.fixture
def fake():
    """Bind a fresh FakeWin for the duration of one test."""
    be = FakeWin()
    winlayer.set_backend(be)
    try:
        yield be
    finally:
        winlayer.reset_backend()


@pytest.fixture
def actlog(tmp_path, monkeypatch):
    """Redirect the §7 action log into the test's tmp dir."""
    path = tmp_path / 'actions.log'
    monkeypatch.setenv('RAPHAEL_ACTION_LOG', str(path))
    return path


@pytest.fixture
def lane_instance(monkeypatch):
    """Isolated instance environment (pc-control lane)."""
    monkeypatch.setenv('RAPHAEL_INSTANCE', 'pc-control')
    monkeypatch.delenv('RAPHAEL_PORT', raising=False)
    monkeypatch.delenv('RAPHAEL_TOKEN_PATH', raising=False)
    monkeypatch.delenv('RAPHAEL_ACTION_LOG', raising=False)
    return 'pc-control'


@pytest.fixture
def main_instance(monkeypatch):
    """Explicit main instance (today's defaults)."""
    monkeypatch.delenv('RAPHAEL_INSTANCE', raising=False)
    monkeypatch.delenv('RAPHAEL_PORT', raising=False)
    monkeypatch.delenv('RAPHAEL_TOKEN_PATH', raising=False)
    monkeypatch.delenv('RAPHAEL_ACTION_LOG', raising=False)
    return 'main'

