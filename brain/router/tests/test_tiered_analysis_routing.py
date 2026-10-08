"""Wave 5: Analysis-mode routing — tier-aware model policy + usage accounting.

Raphael's Wave-5 features add purposes `analysis` / `simulation`. Contract:
- those purposes route to the DEEP tier (bigger model, tie → longest/biggest
  id), even when tools are attached — depth over speed;
- normal turns keep Rule 15 (fast tier: `chat`/`ack` → fast, tools → strong);
- `grok`/`kimi` (MODEL_POLICY "never") stay unreachable in every tier;
- usage accounting buckets the new purposes per-purpose in `usage_status()`.
"""
from __future__ import annotations

import pytest

import brain.router as router
from brain.router.roles import ModelInfo, pick
from brain.router.tests.conftest import make_config


def _router(tmp_path, **kw):
    cfg = make_config(tmp_path, ["mock"], **kw)
    router.reset_router()
    return router.init_router(cfg)


# --------------------------------------------------------------------------- #
# policy wiring (code defaults + lane fragment)
# --------------------------------------------------------------------------- #
def test_config_maps_analysis_and_simulation_to_deep() -> None:
    import os
    saved = os.environ.pop("RAPHAEL_PROFILE", None)
    try:
        cfg = router.load_config()
    finally:
        if saved is not None:
            os.environ["RAPHAEL_PROFILE"] = saved
    pr = cfg.providers.purpose_roles
    assert pr["analysis"] == "deep"
    assert pr["simulation"] == "deep"
    # Rule 15 untouched for normal turns
    assert pr["chat"] == "fast"
    assert pr["ack"] == "fast"
    assert pr["tool"] == "strong"
    assert pr["plan"] == "strong"


def test_role_for_prefers_depth_over_the_tools_rule(tmp_path) -> None:
    rt = _router(tmp_path)
    tools = [{"type": "function",
              "function": {"name": "shell", "parameters": {"type": "object"}}}]
    assert rt._role_for("analysis", tools) == "deep"     # depth beats tools→strong
    assert rt._role_for("analysis", None) == "deep"
    assert rt._role_for("simulation", tools) == "deep"
    # latency lever #2 (dispatch 2026-10-08): tools merely AVAILABLE in a
    # chat turn must NOT escalate — purpose owns the tier
    assert rt._role_for("chat", tools) == "fast"         # was "strong" (bug)
    assert rt._role_for("chat", None) == "fast"
    assert rt._role_for("ack", tools) == "fast"
    # strong path intact for its purposes (no regressions)
    assert rt._role_for("tool", tools) == "strong"
    assert rt._role_for("tool", None) == "strong"
    assert rt._role_for("plan", tools) == "strong"
    # unknown purpose + attached tools stays conservative
    assert rt._role_for("never-heard-of", tools) == "strong"
    assert rt._role_for("never-heard-of", None) == "fast"


# --------------------------------------------------------------------------- #
# deep-tier selection
# --------------------------------------------------------------------------- #
def test_deep_role_prefers_biggest_on_tie() -> None:
    models = [
        ModelInfo("aaa-pro", "x"),
        ModelInfo("zzzzzzzzzz-pro", "x"),      # same hint score, bigger id
        ModelInfo("tiny-7b", "x"),             # no deep hint → 0
    ]
    assert pick(models, "deep").id == "zzzzzzzzzz-pro"
    # …while strong keeps first-seen behavior (existing contract)
    assert pick(models, "strong").id == "aaa-pro"


def test_deep_role_scores_bigger_tiers_higher() -> None:
    models = [
        ModelInfo("tiny-flash-7b", "x"),
        ModelInfo("workhorse-plus-70b", "x"),
        ModelInfo("mid-pro", "x"),
    ]
    assert pick(models, "deep").id == "workhorse-plus-70b"


def test_deep_denies_never_models() -> None:
    never = [ModelInfo("grok-4.7", "x"), ModelInfo("kimi-k3", "x")]
    assert pick(never, "deep") is None
    assert pick([ModelInfo("deepseek-v4-pro", "x")], "deep").id == "deepseek-v4-pro"


# --------------------------------------------------------------------------- #
# end-to-end through the facade (mock provider)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_analysis_purpose_uses_deep_model(tmp_path) -> None:
    rt = _router(tmp_path)
    out = await rt.chat([{"role": "user", "content": "deep dive"}],
                        purpose="analysis")
    assert out["model"] == "mock-large"        # deep hints ("large") over fast
    out_tools = await rt.chat(
        [{"role": "user", "content": "deep dive with tools"}],
        tools=[{"type": "function", "function": {
            "name": "shell", "parameters": {"type": "object"}}}],
        purpose="analysis")
    assert out_tools["model"] == "mock-large"  # depth STILL wins over tools→strong


@pytest.mark.asyncio
async def test_simulation_purpose_uses_deep_model(tmp_path) -> None:
    rt = _router(tmp_path)
    out = await rt.chat([{"role": "user", "content": "simulate"}],
                        purpose="simulation")
    assert out["model"] == "mock-large"


@pytest.mark.asyncio
async def test_normal_turns_stay_fast(tmp_path) -> None:
    """Rule 15: everyday turns must not pay the deeper tier."""
    rt = _router(tmp_path)
    chat = await rt.chat([{"role": "user", "content": "hi"}])
    assert chat["model"] == "mock-instant"
    ack = await rt.chat([{"role": "user", "content": "ok"}], purpose="ack")
    assert ack["model"] == "mock-instant"
    # chat purpose + tools OFFERED → fast tier now (dispatch 2026-10-08)
    with_tools = await rt.chat(
        [{"role": "user", "content": "run this"}],
        tools=[{"type": "function", "function": {
            "name": "shell", "parameters": {"type": "object"}}}])
    assert with_tools["model"] == "mock-instant"        # tools available ≠ invoked
    # …while an explicit tool-purpose turn keeps the strong slot
    tool_turn = await rt.chat(
        [{"role": "user", "content": "run this for real"}],
        tools=[{"type": "function", "function": {
            "name": "shell", "parameters": {"type": "object"}}}],
        purpose="tool")
    assert tool_turn["model"] == "mock-large"           # strong, as before


# --------------------------------------------------------------------------- #
# usage accounting for the new purposes
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_usage_accounting_buckets_new_purposes(tmp_path) -> None:
    rt = _router(tmp_path)
    await rt.chat([{"role": "user", "content": "a"}], purpose="analysis")
    await rt.chat([{"role": "user", "content": "b"}], purpose="analysis")
    await rt.chat([{"role": "user", "content": "c"}], purpose="simulation")
    await rt.chat([{"role": "user", "content": "d"}])          # chat

    status = await rt.usage_status()
    by_purpose = status["by_purpose"]
    assert by_purpose["analysis"]["calls"] == 2
    assert by_purpose["analysis"]["errors"] == 0
    assert by_purpose["analysis"]["input"] > 0
    assert by_purpose["simulation"]["calls"] == 1
    assert by_purpose["chat"]["calls"] == 1

    # the raw log carries the purpose as task_kind (INTERFACES §a usage tag)
    import json
    lines = [json.loads(l) for l in
             cfg_lines(rt.config.usage_log_path)]
    assert {r["task_kind"] for r in lines} >= {"analysis", "simulation", "chat"}


def cfg_lines(path):
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.mark.asyncio
async def test_analysis_failures_still_logged_under_their_purpose(tmp_path) -> None:
    rt = _router(tmp_path)
    import pytest as _pytest
    with _pytest.raises(router.RouterError):
        await rt.chat([{"role": "user", "content": "mock_fail:E_PROVIDER_5XX"}],
                      purpose="analysis")
    status = await rt.usage_status()
    assert status["by_purpose"]["analysis"]["errors"] == 1
    assert status["errors"] == {"E_PROVIDER_5XX": 1}
