"""Model-capability learning (dispatch 2026-10-08, zen tool-slot finding).

Evidence-first scoping (live probes, 2026-10-08):
    zen gemini-3.5-flash-lite (fast pick): plain/stream/tools ALL → 400
        ModelProtocolUnsupported  (model wholly unusable, not a tool issue)
    zen mistral-large-4   (strong):      plain ✓ stream ✓ tools ✓ tool_calls ✓
So the defect is MODEL-level, not provider-level: a bad model that the fast
hints pick must be learned-and-skipped, without tripping the breaker and
without banning zen from tool slots (which would break agent-turn failover).

Pinned here:
  - 400 'does not support this protocol' → model dead for ALL uses, re-picked
    within the same provider (no failover, breaker untouched);
  - 400 'tool calling is not supported'  → model dead for TOOLS only; plain
    chat still uses it (zen keeps serving non-tool turns);
  - every model dead → clean no_model failover to the next provider;
  - stream path learns too (pre-first-delta).
"""
from __future__ import annotations

import pytest

import brain.router as router
from brain.router import RouterError
from brain.router.roles import ModelInfo
from brain.router.tests.conftest import make_config

PROTOCOL_400 = (400, {},
                b'{"type":"error","error":{"type":"ModelProtocolUnsupported",'
                b'"message":"Model does not support this protocol."}}')
TOOL_400 = (400, {},
            b'{"error":{"message":"`tool calling` is not supported '
            b'with this model","type":"invalid_request_error"}}')


def _mk(tmp_path, make_server, chain, models, **kw):
    srv = make_server(models=models, free_suffix=False)
    cfg = make_config(tmp_path, list(chain), zen_url=srv.url, groq_url=srv.url,
                      **kw)
    router.reset_router()
    return router.init_router(cfg), srv


@pytest.mark.asyncio
async def test_dead_model_learned_and_repicked_same_provider(
        tmp_path, make_server, keys) -> None:
    rt, srv = _mk(tmp_path, make_server, ["zen_free"],
                  [{"id": "flash-lite-free"}, {"id": "plain-good-free"}])
    srv.model_script["flash-lite-free"] = PROTOCOL_400

    out = await rt.chat([{"role": "user", "content": "hi"}])   # fast → lite first
    assert out["provider"] == "zen_free"
    assert out["model"] == "plain-good-free"        # re-picked SAME provider
    order = [r["body"] for r in srv.chat_requests]
    assert len(order) == 2                          # strike, then good model
    assert b'"flash-lite-free"' in order[0]
    assert b'"plain-good-free"' in order[1]
    # permanent incapability ≠ provider ill-health → breaker untouched
    assert rt._stats["zen_free"].circuit.state.value == "closed"

    await rt.chat([{"role": "user", "content": "again"}])
    models_hit = [__import__("json").loads(r["body"])["model"]
                  for r in srv.chat_requests]
    assert models_hit[2] == "plain-good-free"       # learned: lite never again
    assert models_hit.count("flash-lite-free") == 1


@pytest.mark.asyncio
async def test_tools_only_model_keeps_serving_plain_chat(
        tmp_path, make_server, keys) -> None:
    """The coordinator's WHY (agent-turn failover) — non-tool turns on the
    same provider must keep working after a tool-400 strike."""
    rt, srv = _mk(tmp_path, make_server, ["zen_free"],
                  [{"id": "flash-shy-free"}, {"id": "plain-good-free"}])
    srv.tool_fail_models.add("flash-shy-free")

    with_tools = [{"type": "function", "function": {
        "name": "shell", "parameters": {"type": "object", "properties": {},
                                        "additionalProperties": False}}}]
    out = await rt.chat([{"role": "user", "content": "run it"}], tools=with_tools)
    assert out["model"] == "plain-good-free"        # shy model skipped for tools

    plain = await rt.chat([{"role": "user", "content": "just chat"}])
    assert plain["model"] == "flash-shy-free"       # still fine WITHOUT tools
    assert rt._stats["zen_free"].circuit.state.value == "closed"


@pytest.mark.asyncio
async def test_all_models_dead_fails_over_cleanly(tmp_path, make_server, keys) -> None:
    zen_srv = make_server(models=[{"id": "flash-lite-free"},
                                  {"id": "plain-good-free"}], free_suffix=False)
    zen_srv.model_script["flash-lite-free"] = PROTOCOL_400
    zen_srv.model_script["plain-good-free"] = PROTOCOL_400
    groq_srv = make_server(free_suffix=False)
    cfg = make_config(tmp_path, ["zen_free", "groq"],
                      zen_url=zen_srv.url, groq_url=groq_srv.url, max_retries=1)
    router.reset_router()
    rt = router.init_router(cfg)
    out = await rt.chat([{"role": "user", "content": "hi"}])
    assert out["provider"] == "groq"                # zen exhausted → failover
    assert rt._stats["zen_free"].circuit.state.value == "closed"  # no breaker
    assert len(zen_srv.chat_requests) == 2          # both zen models tried once


@pytest.mark.asyncio
async def test_stream_path_learns_too(tmp_path, make_server, keys) -> None:
    rt, srv = _mk(tmp_path, make_server, ["zen_free"],
                  [{"id": "flash-lite-free"}, {"id": "plain-good-free"}])
    srv.model_script["flash-lite-free"] = PROTOCOL_400

    with pytest.raises(RouterError):                # only the dead model known yet
        async for _ in rt.chat([{"role": "user", "content": "hi"}], stream=True):
            pass
    events = [ev async for ev in
              rt.chat([{"role": "user", "content": "again"}], stream=True)]
    final = [e for e in events if "finish" in e][0]
    assert final["model"] == "plain-good-free"      # learned across calls
    models_hit = [__import__("json").loads(r["body"])["model"]
                  for r in srv.chat_requests]
    assert models_hit.count("flash-lite-free") == 1 # struck exactly once


def test_mark_model_unsupported_semantics() -> None:
    from brain.router.provider import Provider
    from brain.router.config import RouterConfig, LocalModelSettings, RouterSettings
    cfg = RouterConfig(
        providers=RouterSettings(
            chain=["x"], allow_go_runtime=False, allow_paid_runtime=True,
            allow_free_models_for_personal_data=False,
            zen_base_url="http://127.0.0.1:9", go_base_url="http://127.0.0.1:9",
            discovery_interval_s=3600, max_calls_per_minute=100,
            benchmark_ranking_path="/tmp/r.json"),
        local_model=LocalModelSettings(), repo_root=Path("/tmp"))
    import asyncio

    prov = Provider(cfg)
    prov._models = [ModelInfo("bad", "x"), ModelInfo("shy", "x"),
                    ModelInfo("good", "x")]
    prov._expires_at = 9e12
    prov.mark_model_unsupported("bad")                       # dead entirely
    prov.mark_model_unsupported("shy", tools_only=True)      # tools only

    async def scenario():
        first = await prov.pick("fast")              # bad gone (min-len → shy)
        for_tools = await prov.pick("fast", tools=True)   # +shy gone → good
        without_tools = await prov.pick("fast")      # shy fine WITHOUT tools
        return first, for_tools, without_tools

    first, for_tools, without_tools = asyncio.run(scenario())
    assert first.id in ("shy", "good")
    assert for_tools.id == "good"                    # shy gone for tools
    assert without_tools.id == "shy"


from pathlib import Path  # noqa: E402  (used by the unit above)
