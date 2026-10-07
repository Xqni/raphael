"""Fixtures for router unit tests — ALL HTTP stays on 127.0.0.1, no keys.

Rules enforced here (AGENT_RULES §5/§7):
- no external network, no real API keys, key values never asserted or printed;
- `RAPHAEL_INSTANCE=router` + `RAPHAEL_ENV_FILE` pointed at a throwaway file
  so a developer's real `.env` can never leak into an assertion;
- usage log lands in tmp_path (never the repo's usage.jsonl).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brain.router.config import (  # noqa: E402
    LocalModelSettings,
    PrivacySettings,
    RouterConfig,
    RouterSettings,
    VisionSettings,
    VoiceSettings,
)
from brain.router.tests.mockserver import ScriptedServer  # noqa: E402

os.environ.setdefault("RAPHAEL_INSTANCE", "router")


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No real keys, no private mode, no foreground hook, isolated secrets file."""
    empty_env = tmp_path / "empty.env"
    if not empty_env.exists():
        empty_env.write_text("# test env — deliberately empty\n", encoding="utf-8")
    monkeypatch.setenv("RAPHAEL_ENV_FILE", str(empty_env))
    for name in ("GROQ_API_KEY", "OPENCODE_API_KEY", "ZEN_API_KEY",
                 "OPENCODE_ZEN_KEY", "GITHUB_TOKEN", "RAPHAEL_PRIVATE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("brain.router.privacy._secret_cache", None)
    monkeypatch.setattr("brain.router.privacy._private", False)
    monkeypatch.setattr("brain.router.privacy._foreground_check", None)
    yield


@pytest.fixture(autouse=True)
def _reset_singleton():
    from brain.router import core
    core.reset_router()
    yield
    core.reset_router()


def make_config(
    tmp_path: Path,
    chain: list[str],
    *,
    groq_url: str = "http://127.0.0.1:9",
    zen_url: str = "http://127.0.0.1:9",
    go_url: str = "http://127.0.0.1:9",
    keys: dict[str, str] | None = None,
    vision_provider: str = "cloud",
    stt_engine: str = "groq",
    ollama_url: str = "http://127.0.0.1:9",
    blocklist: tuple[str, ...] = ("1Password", "KeePass", "Banking"),
    profile: str | None = None,
    **settings_kw,
) -> RouterConfig:
    """Explicit RouterConfig for tests (no YAML, no real endpoints)."""
    kw = dict(
        chain=chain,
        allow_go_runtime=False,
        allow_paid_runtime=False,
        allow_free_models_for_personal_data=False,
        zen_base_url=zen_url,
        go_base_url=go_url,
        groq_base_url=groq_url,
        discovery_interval_s=3600,
        max_calls_per_minute=1000,
        benchmark_ranking_path=str(tmp_path / "rank.json"),
        usage_log_path=str(tmp_path / "usage.jsonl"),
        max_retries=1,
        backoff_base_s=0.01,
        backoff_cap_s=0.05,
        request_timeout_s=5.0,
        stream_timeout_s=5.0,
        discovery_timeout_s=3.0,
        rpm={"groq": 1000, "zen_free": 1000, "go": 1000, "ollama": 1000,
             "mock": 1000},
        tpm={"groq": 1_000_000, "zen_free": 1_000_000, "go": 1_000_000,
             "ollama": 1_000_000, "mock": 1_000_000},
    )
    kw.update(settings_kw)
    return RouterConfig(
        providers=RouterSettings(**kw),
        local_model=LocalModelSettings(
            candidates=["qwen3.5:4b"], ollama_url=ollama_url),
        repo_root=tmp_path,
        profile=profile or ("cloud_temp" if vision_provider == "cloud" else "local"),
        privacy=PrivacySettings(blocklist_apps=tuple(blocklist)),
        vision=VisionSettings(provider=vision_provider,
                              max_bytes=int(kw.get("vision_max_bytes", 4_000_000))),
        voice=VoiceSettings(stt_engine=stt_engine),
    )


@pytest.fixture
def make_server():
    """Factory: `srv = make_server(models=[...])` → started ScriptedServer."""
    servers: list[ScriptedServer] = []

    def _make(models=None, free_suffix=True, **kw) -> ScriptedServer:
        srv = ScriptedServer(models=models, free_suffix=free_suffix, **kw)
        srv.start()
        servers.append(srv)
        return srv

    yield _make
    for srv in servers:
        srv.stop()


@pytest.fixture
def config_factory(tmp_path: Path):
    return lambda *a, **kw: make_config(tmp_path, *a, **kw)


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch):
    """Fake (non-secret) keys for the LOCAL mock server only."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key_not_real_0001")
    monkeypatch.setenv("OPENCODE_API_KEY", "oc_test_key_not_real_0002")
