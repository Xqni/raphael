"""Router unit tests: resilience primitives, policy, role mapping, JSON repair,
and the legacy `acquire_model`/`complete` seam that `brain/llm.py` depends on.

HTTP is always mocked (conftest + ScriptedServer) — no network, no keys.
"""
from __future__ import annotations

import json

import pytest

import brain.router as router
from brain.router import RouterError
from brain.router.config import LocalModelSettings, RouterSettings
from brain.router.core import CircuitBreaker, RateLimiter, TokenBudget
from brain.router.jsonrepair import repair_arguments, repair_json
from brain.router.tests.conftest import make_config

# --------------------------------------------------------------------------- #
# resilience primitives
# --------------------------------------------------------------------------- #
def test_circuit_breaker_transitions() -> None:
    cb = CircuitBreaker(failure_threshold=2, success_threshold=1, timeout_s=0.01)
    now = 0.0
    assert cb.can_proceed(now)
    cb.record_failure(now)
    assert cb.state.value == "closed"
    cb.record_failure(now)
    assert cb.state.value == "open"
    now += 0.05                                       # beyond jittered cooldown
    assert cb.can_proceed(now)
    assert cb.state.value == "half-open"
    cb.record_success()
    assert cb.state.value == "closed"


def test_circuit_breaker_half_open_failure_reopens() -> None:
    cb = CircuitBreaker(failure_threshold=1, success_threshold=1, timeout_s=0.01)
    cb.record_failure(0.0)
    assert cb.can_proceed(1.0)                        # cooldown elapsed
    cb.record_failure(1.0)
    assert cb.state.value == "open"


def test_rate_limiter_window() -> None:
    rl = RateLimiter(max_calls=2, window_s=60.0)
    now = 0.0
    assert rl.allow(now)
    assert rl.allow(now)
    assert not rl.allow(now)
    assert rl.allow(now + 61.0)                       # window slides


def test_token_budget_window() -> None:
    tb = TokenBudget(max_tokens=100, window_s=60.0)
    assert tb.allow(0.0, 60)
    tb.record(0.0, 60)
    assert not tb.allow(1.0, 60)                      # 60 + 60 > 100
    assert tb.allow(61.0, 60)                         # old usage expired


# --------------------------------------------------------------------------- #
# policy + role mapping units
# --------------------------------------------------------------------------- #
def test_policy_excluded_models() -> None:
    from brain.router.policy import is_excluded
    assert is_excluded("slut")
    assert is_excluded("slut:latest")
    assert is_excluded("  SLUT  ")
    assert not is_excluded("qwen3.5:4b")
    assert not is_excluded("mimo-v2.6-flash-free")
    assert not is_excluded("")


@pytest.mark.asyncio
async def test_zen_free_ids_filtered_by_exclusion() -> None:
    import time as _time
    from brain.router.zen import ZenDiscovery, ZenModel

    zd = ZenDiscovery("https://example.invalid")
    zd._models = [
        ZenModel(id="mimo-v2.6-flash-free", free=True),
        ZenModel(id="slut", free=True),
        ZenModel(id="slut:latest", free=True),
    ]
    zd._expires_at = _time.monotonic() + 999
    assert await zd.get_free_model_ids() == ["mimo-v2.6-flash-free"]


@pytest.mark.asyncio
async def test_zen_free_flag_defaults_to_paid_without_metadata() -> None:
    """Zen's live /models has no `free` field — non-`-free` ids are PAID."""
    from brain.router.zen import ZenDiscovery

    parsed = ZenDiscovery._parse_models({
        "data": [{"id": "claude-opus-5"}, {"id": "mimo-flash-free"},
                 {"id": "gpt-6-sol"}],
    })
    assert [m.free for m in parsed] == [False, True, False]


@pytest.mark.asyncio
async def test_ollama_denylist_filters_excluded() -> None:
    from brain.router.ollama import OllamaProvider

    op = OllamaProvider()

    async def fake_tags():
        return [{"name": "qwen3.5:4b"}, {"name": "slut:latest"}]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(op, "_fetch_tags", fake_tags)
        models = await op.list_models()
    assert models == ["qwen3.5:4b"]


def test_role_pick_prefers_hints_then_capability() -> None:
    from brain.router.roles import ModelInfo, pick

    models = [
        ModelInfo("llama-prompt-guard-2-22m", "p", capabilities=frozenset()),
        ModelInfo("allam-2-7b", "p", capabilities=frozenset()),
        ModelInfo("giant-plus-70b", "p", capabilities=frozenset()),
        ModelInfo("whisper-large-v3", "p", capabilities=frozenset({"audio"})),
    ]
    assert pick(models, "fast").id == "allam-2-7b"
    assert pick(models, "strong").id == "giant-plus-70b"
    assert pick(models, "stt").id == "whisper-large-v3"
    assert pick(models, "vision") is None            # never guessed for images
    # capability metadata beats hints
    tagged = [ModelInfo("small-7b", "p", capabilities=frozenset({"vision"}))]
    assert pick(tagged, "vision").id == "small-7b"


# --------------------------------------------------------------------------- #
# JSON repair (tool arguments)
# --------------------------------------------------------------------------- #
def test_repair_json_variants() -> None:
    assert repair_json('{"a": 1}') == {"a": 1}
    assert repair_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert repair_json('{"a": 1,}') == {"a": 1}
    assert repair_json("{'a': 1}") == {"a": 1}
    assert repair_json('{a: 1}') == {"a": 1}
    assert repair_json('{"a": "unfinished') == {"a": "unfinished"}
    assert repair_json('{"a": [1, 2') == {"a": [1, 2]}
    assert repair_json("not json") is None
    assert repair_json(None) is None


def test_repair_arguments_keeps_raw_when_unrecoverable() -> None:
    args, repaired = repair_arguments('{"ok": true,}')
    assert args == {"ok": True} and repaired is True
    args, repaired = repair_arguments({"already": "dict"})
    assert args == {"already": "dict"} and repaired is False
    args, repaired = repair_arguments("total garbage")
    assert args == {"_raw": "total garbage"} and repaired is True
    args, repaired = repair_arguments(None)
    assert args == {} and repaired is False


# --------------------------------------------------------------------------- #
# legacy seam (brain/llm.py → acquire_model + complete)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_acquire_model_returns_chain_head(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"])
    router.reset_router()
    router.init_router(cfg)
    provider, model = await router.acquire_model(task_kind="chat")
    assert provider == "mock"
    assert model == "mock-instant"
    provider, model = await router.acquire_model(task_kind="plan")
    assert model == "mock-large"                      # plan → strong slot


@pytest.mark.asyncio
async def test_acquire_model_raises_when_chain_empty(tmp_path) -> None:
    from brain.router import ProviderUnavailable
    cfg = make_config(tmp_path, ["go"], allow_go_runtime=False)
    router.reset_router()
    router.init_router(cfg)
    with pytest.raises(ProviderUnavailable):
        await router.acquire_model()


@pytest.mark.asyncio
async def test_complete_returns_call_result_never_raises(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"])
    router.reset_router()
    rt = router.init_router(cfg)
    provider, model = await rt.acquire_model()
    res = await rt.complete(provider, model, prompt="what time is it",
                            task_kind="chat")
    assert res.ok is True
    assert res.text.startswith("Mock reply to:")
    assert res.provider == provider
    assert res.outcome.value == "success"
    assert res.tokens_input > 0


@pytest.mark.asyncio
async def test_complete_reports_failure_with_code(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"])
    router.reset_router()
    rt = router.init_router(cfg)
    res = await rt.complete("mock", "mock-instant",
                            prompt="mock_fail:E_PROVIDER_5XX")
    assert res.ok is False
    assert res.error_code == "E_PROVIDER_5XX"


@pytest.mark.asyncio
async def test_complete_refused_in_private_mode(tmp_path) -> None:
    from brain.router.privacy import set_private_mode
    cfg = make_config(tmp_path, ["mock"])
    router.reset_router()
    rt = router.init_router(cfg)
    set_private_mode(True)
    try:
        res = await rt.complete("mock", "mock-instant", prompt="hi")
        assert res.ok is False
        assert res.error_code == "E_OFFLINE"
    finally:
        set_private_mode(False)


@pytest.mark.asyncio
async def test_legacy_health_check_shape(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"])
    router.reset_router()
    rt = router.init_router(cfg)
    legacy = await rt.health_check()
    assert legacy == {"mock": True}
    full = await rt.health()
    assert full["ok"] is True


@pytest.mark.asyncio
async def test_usage_log_written_and_structured(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"])
    router.reset_router()
    rt = router.init_router(cfg)
    await rt.chat([{"role": "user", "content": "log me"}], purpose="ack")
    lines = cfg.usage_log_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines, "usage.jsonl must get a line per call"
    record = json.loads(lines[-1])
    assert record["provider"] == "mock"
    assert record["task_kind"] == "ack"
    assert record["outcome"] == "success"
    assert record["tokens_input"] >= 0


# --------------------------------------------------------------------------- #
# settings sanity (older constructions must keep working)
# --------------------------------------------------------------------------- #
def test_router_settings_backwards_compatible_defaults() -> None:
    settings = RouterSettings(
        chain=["zen_free", "go", "ollama"],
        allow_go_runtime=False,
        allow_paid_runtime=False,
        allow_free_models_for_personal_data=False,
        zen_base_url="https://example.com/zen/v1",
        go_base_url="https://example.com/zen/go/v1",
        discovery_interval_s=3600,
        max_calls_per_minute=100,
        benchmark_ranking_path="/tmp/rank.json",
    )
    assert settings.groq_base_url == "https://api.groq.com/openai/v1"
    assert settings.role_hints["stt"]
    assert settings.rpm_for("groq") == 30
    assert settings.rpm_for("unknown") == 100        # falls back to max_calls
    assert settings.tpm_for("zen_free") == 12000
    local = LocalModelSettings()
    assert local.enabled is False
    assert local.ollama_url == "http://127.0.0.1:11434"


@pytest.mark.asyncio
async def test_module_facade_helpers_wired(tmp_path) -> None:
    """`brain.router.chat(...)` module-level path (what other lanes import)."""
    cfg = make_config(tmp_path, ["mock"])
    router.reset_router()
    router.init_router(cfg)
    out = await router.chat([{"role": "user", "content": "via module"}])
    assert out["provider"] == "mock"
    with pytest.raises(RouterError):
        await router.chat([], purpose="tool")


def test_speed_mandate_fast_hint_and_never_models_denied() -> None:
    """Speed mandate (BUGS-WAVE2/PAID_USAGE 2026-10-07): flash-class/mimo get
    the fast slot, and MODEL_POLICY 'never' models (grok 2/6, kimi 3/15) are
    unreachable for chat/vision even if a paid chain is enabled."""
    from brain.router.roles import ModelInfo, pick

    go_models = [
        ModelInfo("opencode-go/gpt-6-sol", "go"),
        ModelInfo("opencode-go/mimo-v2.5", "go"),
        ModelInfo("opencode-go/grok-4.7", "go"),
        ModelInfo("opencode-go/kimi-k3", "go"),
    ]
    fast = pick(go_models, "fast")
    assert fast is not None
    assert fast.id == "opencode-go/mimo-v2.5"        # fast hint beats length fallback

    only_never = [ModelInfo("opencode-go/grok-4.7", "go"),
                  ModelInfo("opencode-go/kimi-k3", "go")]
    assert pick(only_never, "fast") is None          # denied → no selection
    assert pick(only_never, "vision") is None        # denied for vision too

    # deny never blocks a normal model
    assert pick([ModelInfo("allam-2-7b", "groq")], "fast").id == "allam-2-7b"
