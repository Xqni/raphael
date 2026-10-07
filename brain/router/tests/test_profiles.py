"""Profile switching + config load order (INTERFACES §c) — Wave 6 prep.

`cloud_temp` (current) must chain cloud providers only; `local` (Wave 6
cutover) must flip to `[zen_free, go, ollama]`, local STT and local vision —
and the local code paths stay alive and tested the whole time.
"""
from __future__ import annotations

import pytest

import brain.router as router
from brain.router import RouterError
from brain.router.config import load_config
from brain.router.tests.conftest import make_config

# --------------------------------------------------------------------------- #
# config load order
# --------------------------------------------------------------------------- #
def test_load_order_base_then_fragment_then_profile(tmp_path, monkeypatch) -> None:
    (tmp_path / "config.yaml").write_text(
        "profile: cloud_temp\n"
        "providers:\n"
        "  chain: [groq, zen_free]\n"
        "  groq_base_url: http://base-a\n"
        "router:\n"
        "  rpm: { groq: 11 }\n"
        "voice:\n"
        "  stt_engine: groq\n"
        "profiles:\n"
        "  local:\n"
        "    profile: local\n"
        "    providers: { chain: [zen_free, ollama] }\n"
        "    voice: { stt_engine: local }\n",
        encoding="utf-8",
    )
    frag_dir = tmp_path / "config.d"
    frag_dir.mkdir()
    (frag_dir / "router.yaml").write_text(
        "router:\n  rpm: { groq: 22 }\n  max_retries: 7\n", encoding="utf-8")

    monkeypatch.delenv("RAPHAEL_PROFILE", raising=False)
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.profile == "cloud_temp"
    assert cfg.providers.chain == ["groq", "zen_free"]
    assert cfg.providers.rpm["groq"] == 22          # fragment wins over base
    assert cfg.providers.max_retries == 7
    assert cfg.providers.groq_base_url == "http://base-a"   # untouched by fragment
    assert cfg.voice.stt_engine == "groq"

    monkeypatch.setenv("RAPHAEL_PROFILE", "local")   # env wins (INTERFACES §c)
    cfg_local = load_config(tmp_path / "config.yaml")
    assert cfg_local.profile == "local"
    assert cfg_local.providers.chain == ["zen_free", "ollama"]
    assert cfg_local.voice.stt_engine == "local"
    assert cfg_local.providers.rpm["groq"] == 22     # fragment still applies


def test_repo_config_is_cloud_temp_chain() -> None:
    """The committed base config (integrator-owned) drives today's profile."""
    import os
    saved = os.environ.pop("RAPHAEL_PROFILE", None)
    try:
        cfg = load_config()
    finally:
        if saved is not None:
            os.environ["RAPHAEL_PROFILE"] = saved
    assert cfg.profile == "cloud_temp"
    assert cfg.providers.chain == ["groq", "zen_free"]
    assert cfg.providers.allow_go_runtime is False
    assert cfg.providers.allow_paid_runtime is False
    assert cfg.voice.stt_engine == "groq"
    assert cfg.vision.provider == "cloud"
    assert cfg.local_model.enabled is False
    # vision-only paid slot (user approval, docs/PAID_USAGE.md) — gate + cap
    # come straight from the integrator-owned config.yaml
    assert cfg.providers.allow_vision_paid is True
    assert cfg.providers.vision_paid_daily_cap_usd == 1.00
    assert cfg.providers.allow_go_runtime is False
    assert cfg.providers.allow_paid_runtime is False
    assert cfg.providers.vision_paid_price_per_mtok["input"] > 0


def test_repo_config_profile_local_overlay(monkeypatch) -> None:
    """Wave 6 cutover: profile local → local chain, local STT/vision."""
    monkeypatch.setenv("RAPHAEL_PROFILE", "local")
    cfg = load_config()
    assert cfg.profile == "local"
    assert cfg.providers.chain == ["zen_free", "go", "ollama"]
    assert cfg.voice.stt_engine == "local"
    assert cfg.vision.provider == "local"
    assert cfg.local_model.enabled is True
    # Go stays gated even in the local profile
    assert cfg.providers.allow_go_runtime is False


def test_router_mock_env_switch(monkeypatch) -> None:
    monkeypatch.setenv("RAPHAEL_ROUTER_MOCK", "1")
    cfg = load_config()
    assert cfg.providers.chain == ["mock"]


# --------------------------------------------------------------------------- #
# profile `local` runtime behaviour (kept alive for the Wave 6 cutover)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_profile_local_chat_goes_through_ollama(
        tmp_path, make_server) -> None:
    srv = make_server()                              # /api/tags + /api/chat
    cfg = make_config(tmp_path, ["ollama"], ollama_url=srv.url, profile="local")
    router.reset_router()
    router.init_router(cfg)
    out = await router.chat([{"role": "user", "content": "hello"}])
    assert out["provider"] == "ollama"
    assert out["text"].startswith("ollama reply from")
    assert any(r["path"].endswith("/api/tags") for r in srv.requests)  # discovery
    assert any(r["path"].endswith("/api/chat") for r in srv.requests)


@pytest.mark.asyncio
async def test_profile_local_ollama_tool_calls(tmp_path, make_server) -> None:
    srv = make_server()
    srv.ollama_script.append({
        "message": {"role": "assistant", "content": "",
                    "tool_calls": [{"function": {"name": "open_app",
                                                 "arguments": {"name": "notepad"}}}]},
        "done": True, "done_reason": "stop",
        "usage": {"prompt_eval_count": 3, "eval_count": 2},
    })
    cfg = make_config(tmp_path, ["ollama"], ollama_url=srv.url)
    router.reset_router()
    router.init_router(cfg)
    out = await router.chat(
        [{"role": "user", "content": "open notepad"}],
        tools=[{"type": "function", "function": {
            "name": "open_app", "parameters": {"type": "object"}}}])
    assert out["finish"] == "tool_calls"
    assert out["tool_calls"][0]["function"]["name"] == "open_app"
    assert out["tool_calls"][0]["function"]["arguments"] == {"name": "notepad"}


@pytest.mark.asyncio
async def test_local_stt_seam_registration(tmp_path, make_server) -> None:
    """profile local: voice lane registers local STT behind transcribe()."""
    cfg = make_config(tmp_path, ["mock"], stt_engine="local")
    router.reset_router()
    router.init_router(cfg)

    with pytest.raises(RouterError) as exc:
        await router.transcribe(b"RIFF" + b"\x00" * 8)
    assert exc.value.code == "E_LOCAL_DOWN"
    assert exc.value.reason == "stt_not_available"

    async def fake_local(audio: bytes, language=None):
        return {"text": "local transcript", "rtf": 0.42}

    router.set_local_transcriber(fake_local)
    out = await router.transcribe(b"RIFF" + b"\x00" * 8, language="en")
    assert out == {"text": "local transcript", "rtf": 0.42}


@pytest.mark.asyncio
async def test_cloud_stt_engine_ignores_local_seam(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"], stt_engine="groq")
    router.reset_router()
    router.init_router(cfg)

    async def fake_local(audio: bytes, language=None):
        return {"text": "should not be used", "rtf": 0.1}

    router.set_local_transcriber(fake_local)
    out = await router.transcribe(b"RIFF" + b"\x00" * 8)
    assert out["text"].startswith("Mock transcript")   # cloud path (mock provider)
