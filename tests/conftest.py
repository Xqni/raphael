"""Path glue + qa-security hermetic test environment.

Part 1 (integrator, 2026-10-05) — path/CWD glue:
1) repo root on sys.path — tests import repo packages (`import body.win...`)
   as PEP 420 namespace packages, so the root must be importable no matter
   how pytest is invoked;
2) pin CWD to the repo root — conformance tests read repo files via
   CWD-relative paths (`Path("docs/PROTOCOL.md")`).
Both make `cd tests && ./.venv/bin/python -m pytest -q .` work as documented.

Part 2 (qa-security, 2026-10-06) — Wave-2 mock harness environment
(AGENT_RULES §5: isolated instance, mocks only, no live stack):
- RAPHAEL_INSTANCE=qa-security forced for EVERY run (INTERFACES §d);
- temp token + temp DB (never the real ~/.raphael/token, never memory.db);
- RAPHAEL_DISABLE_ROUTER=1 by default — no test can reach a real provider;
  tests that need the router point it at harness.mock_openai explicitly;
- RAPHAEL_DISABLE_BINARY_TTS=1 (starlette TestClient cannot UTF-8-decode
  binary frames — same opt-out as brain/tests/conftest; production stays ON);
- RAPHAEL_FISH_PORT=1 — never main's 8777; plus class-level TTS/STT mocks
  (qa_mock_voice) so NO test can spawn Fish-Speech or load faster-whisper
  (voice tests mock TTS — AGENT_RULES §5);
- RAPHAEL_CONFIRM_TIMEOUT_S=2 — confirm-timeout regressions finish fast.
"""
import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if Path.cwd().resolve() != _ROOT:
    os.chdir(_ROOT)
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

# ---- hermetic env (import-timed values must be set before brain imports) ---
os.environ['RAPHAEL_INSTANCE'] = 'qa-security'   # AGENT_RULES §5: isolated instance
os.environ['RAPHAEL_DISABLE_BINARY_TTS'] = '1'   # TestClient can't decode binary
os.environ['RAPHAEL_DISABLE_ROUTER'] = '1'       # no provider/network unless a test
                                                # explicitly re-points the router
os.environ['RAPHAEL_CONFIRM_TIMEOUT_S'] = '2'    # fast confirm-timeout regressions
os.environ['RAPHAEL_FISH_PORT'] = '1'            # dead port — never main's 8777

_fd, _db = tempfile.mkstemp(prefix='raphael-qa-db-')
os.close(_fd)
os.environ['RAPHAEL_DB_PATH'] = _db

_tok_fd, _token_path = tempfile.mkstemp(prefix='raphael-qa-token-')
os.close(_tok_fd)
QA_TOKEN = 'qa-sentinel-token-' + os.urandom(8).hex()
with open(_token_path, 'w') as _f:
    _f.write(QA_TOKEN)
os.environ['RAPHAEL_TOKEN_PATH'] = _token_path

import pytest  # noqa: E402


@pytest.fixture(scope='session', autouse=True)
def qa_session_env():
    """Session-scoped temp DB/token lifecycle (both NEVER the real ones)."""
    yield
    for p in (_db, _db + '-wal', _db + '-shm', _token_path):
        try:
            os.remove(p)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def qa_reset_before_test(qa_session_env):
    """Per-test isolation, applied BEFORE every test: wipe jobs/journal/state,
    clear auth-ban state on the shared hub singleton, un-pause the engine,
    reset mode flags. (Leftovers come from the previous test; DB/token are
    session-scoped temp files — never the real ones.)"""
    from brain.mode import reset_mode_for_tests
    from brain.ws import get_hub

    os.environ['RAPHAEL_DISABLE_ROUTER'] = '1'  # a test that flips it must restore
    hub = get_hub()
    hub._auth_fails.clear()
    hub._banned_until.clear()
    _wipe_db()
    reset_mode_for_tests()
    try:
        from brain.jobs.engine import get_engine
        eng = get_engine()
        eng.resume()
        eng.confirmer._pending.clear()
    except Exception:  # noqa: BLE001 — engine may not exist yet in pure-unit runs
        pass
    yield
    reset_mode_for_tests()


def _wipe_db():
    try:
        from brain.memory import get_conn
        conn = get_conn()
        try:
            conn.execute('DELETE FROM jobs')
            conn.execute('DELETE FROM journal')
            conn.execute('DELETE FROM state')
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — tables may not exist before first use
        pass


@pytest.fixture(autouse=True)
def qa_guard_real_paths(monkeypatch):
    """Never write MAIN's runtime files from tests: /tmp/raphael-brain.pid
    (the supervisor recycles on it) and the real ~/.raphael/token.
    app.py wraps the pidfile write in try/except OSError — raising is the
    safe, caught path. Everything else passes through untouched."""
    import builtins
    _real_open = builtins.open

    def _guarded(file, mode='r', *args, **kwargs):
        m = str(mode)
        if ('w' in m) or ('a' in m) or ('+' in m):
            path = str(file)
            if path == '/tmp/raphael-brain.pid' or path.endswith('/.raphael/token'):
                raise OSError('qa-security: refusing to write real runtime '
                              f'path from tests: {path}')
        return _real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', _guarded)
    yield


@pytest.fixture(autouse=True)
def qa_mock_voice(monkeypatch):
    """NEVER spawn Fish-Speech or load faster-whisper in tests (AGENT_RULES §5).

    Patches at class level: warmup, speak (tiny deterministic PCM stream),
    ensure_started (hard-fail), and transcribe_result (records the PCM it was
    handed, returns a canned transcript). wake/InterruptController stay REAL
    (pure logic, no hardware). monkeypatch reverts everything at teardown.
    """
    from harness import voicespy
    voicespy.install(monkeypatch)
    yield


@pytest.fixture
def qa_token():
    """The session temp token (never the real ~/.raphael/token)."""
    return QA_TOKEN


@pytest.fixture
def client(qa_token):
    """A lifespan-running TestClient (hub + job engine + agent loop wired)."""
    from fastapi.testclient import TestClient
    from brain.app import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_openai():
    """Ephemeral scripted OpenAI-compatible provider (127.0.0.1:random)."""
    from harness.mock_openai import MockOpenAI
    m = MockOpenAI().start()
    yield m
    m.stop()


@pytest.fixture
def router_to_mock(mock_openai, monkeypatch, tmp_path):
    """Point the REAL brain router at mock_openai: chain=[zen_free] only,
    fake key (presence-only, never a real secret), usage log redirected to
    tmp so no test writes brain/router/usage.jsonl (runtime data, not ours).

    NOTE: builds RouterConfig directly instead of load_config() — load_config
    currently CRASHES on config.yaml's profiles block (naive YAML parser;
    request: qa-security -> router fix-config-loader). The load crash itself
    is pinned by contract/test_config_loader.py."""
    from brain.router import core as router_core
    from brain.router.config import (LocalModelSettings, ProviderEndpoints,
                                     RouterConfig, RouterSettings)

    providers = RouterSettings(
        chain=['zen_free'],
        allow_go_runtime=False,
        allow_paid_runtime=False,
        allow_free_models_for_personal_data=False,
        zen_base_url=mock_openai.base_url,
        go_base_url=ProviderEndpoints().go_base_url,
        discovery_interval_s=3600,
        max_calls_per_minute=1000,
        benchmark_ranking_path='brain/router/benchmark_ranking.json',
    )
    local = LocalModelSettings(candidates=[], text='auto', vision='auto',
                               keep_alive='5m', vision_keep_alive='0',
                               max_concurrency=1,
                               ollama_url=mock_openai.plain_url + '/ollama')
    cfg = RouterConfig(providers=providers, local_model=local,
                       repo_root=router_core.REPO_ROOT)
    monkeypatch.setattr(router_core, '_router', router_core.Router(cfg))
    monkeypatch.setattr(router_core, 'USAGE_LOG_PATH',
                        tmp_path / 'usage.jsonl')
    monkeypatch.setenv('OPENCODE_API_KEY', 'sk-qa-fake-key-not-a-real-secret')
    monkeypatch.delenv('RAPHAEL_DISABLE_ROUTER', raising=False)
    return mock_openai
