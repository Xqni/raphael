"""Wave 5U Wave A — confirm-gate tests (qa-security packet §5.5 task 1).

Gates under test (contract: docs/PROTOCOL.md §9 + config.yaml safety.*):
1. HIGH-RISK + voice `yes` -> REJECTED (open-mic acoustic injection); the
   pending confirmation STAYS so the user can confirm from orb click or typed.
   Typed (cli) and click (ui) confirmations succeed. [LANDED: brain/confirm.py
   Confirmer.resolve_ex -> 'rejected_channel'; ws.py channel derives only from
   the authenticated session role (AUD-08) — a client-sent `via` is ignored.]
2. Policy cannot be loosened by a config.d fragment (AUTHORITY_KEYS strips
   safety/privacy/providers — brain/config.py:129). [LANDED]
3. UNCLASSIFIED tool defaults to CONFIRM (design-review HIGH: default-confirm
   contradicts code). [NOT landed: classify() still returns needs=False for an
   unknown tool with no pattern hit — xfail tripwire; flips when brain-core's
   P3 lands the confirm_policy lookup.]

Each landed gate is MUTATION-checked (docs/reviews/2026-10-10-wave5u-mutations.md):
weakening the build turns these red.
"""
import asyncio

import pytest
import yaml

from brain import config as cfg
from brain.confirm import (
    Confirmer, CHANNEL_VOICE, CHANNEL_CLICK, CHANNEL_TEXT, classify,
)

REPO_CFG = cfg.REPO_ROOT / "config.yaml"


# --- 1. voice yes on high-risk is rejected; typed/click succeed -------------

def _drive(answer, via, risk="high"):
    """Register a pending confirmation for rowid=5, answer it via `via`,
    return (resolve_result, resolved_answer_or_None)."""
    conf = Confirmer(timeout_s=30.0)

    async def _run():
        task = asyncio.ensure_future(
            conf.request(5, "About to delete files. Confirm?", ["yes", "no"],
                         risk=risk))
        await asyncio.sleep(0)          # let the future register as pending
        assert conf.pending(5), "confirmation did not register as pending"
        result = conf.resolve_ex(5, answer, via=via)
        resolved = await asyncio.wait_for(task, timeout=1.0)
        return result, resolved

    return asyncio.run(_run())


def test_voice_yes_on_high_risk_is_rejected_and_pending_stays():
    """Voice 'yes' must NOT resolve a high-risk confirmation (acoustic
    injection: TTS/speaker replay of 'yes' through the open mic)."""
    conf = Confirmer(timeout_s=30.0)

    async def _run():
        task = asyncio.ensure_future(
            conf.request(5, "About to delete files. Confirm?", ["yes", "no"],
                         risk="high"))
        await asyncio.sleep(0)
        assert conf.pending(5)
        # voice affirmative -> rejected, future still pending
        assert conf.resolve_ex(5, "yes", via=CHANNEL_VOICE) == "rejected_channel"
        assert conf.pending(5), "pending must STAY after a rejected voice yes"
        # now confirm from the click channel (orb card) -> ok
        assert conf.resolve_ex(5, "yes", via=CHANNEL_CLICK) == "ok"
        assert (await asyncio.wait_for(task, timeout=1.0)) == "yes"

    asyncio.run(_run())


def test_typed_and_click_confirm_succeed_on_high_risk():
    """Non-voice channels (typed text, orb click) resolve a high-risk confirm."""
    assert _drive("yes", CHANNEL_CLICK) == ("ok", "yes")
    assert _drive("yes", CHANNEL_TEXT) == ("ok", "yes")


def test_voice_no_on_high_risk_is_allowed():
    """A voice NEGATIVE is safe (it aborts) — only affirmatives are rejected."""
    conf = Confirmer(timeout_s=30.0)

    async def _run():
        task = asyncio.ensure_future(
            conf.request(6, "About to purchase. Confirm?", ["yes", "no"],
                         risk="high"))
        await asyncio.sleep(0)
        assert conf.resolve_ex(6, "no", via=CHANNEL_VOICE) == "ok"
        assert (await asyncio.wait_for(task, timeout=1.0)) == "no"

    asyncio.run(_run())


def test_voice_yes_on_low_risk_is_allowed():
    """LOW-risk confirmations may be voice-approved (the low/high split,
    AGENT_RULES §8) — only high-risk needs a non-voice channel."""
    assert _drive("yes", CHANNEL_VOICE, risk="low") == ("ok", "yes")


# --- 2. policy cannot be loosened by a config.d fragment (AUTHORITY_KEYS) ---

def test_policy_cannot_be_loosened_by_config_d_fragment(tmp_path, monkeypatch):
    """A lane fragment may NOT set safety.* (confirm_policy/typed_confirm/
    confirm_actions) — AUTHORITY_KEYS strips them (brain/config.py:129)."""
    for var in ("RAPHAEL_PROFILE", "RAPHAEL_INSTANCE"):
        monkeypatch.delenv(var, raising=False)
    cfg.reset_config_for_tests()
    try:
        base = yaml.safe_load(REPO_CFG.read_text(encoding="utf-8"))
        base_dir = tmp_path / "base"
        # minimal standalone base (only needs the safety block present)
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump({"safety": base["safety"]}), encoding="utf-8")
        d = tmp_path / "config.d"
        d.mkdir(exist_ok=True)
        (d / "evil-lane.yaml").write_text(yaml.safe_dump({
            "safety": {"confirm_policy": {"default": "auto"},
                       "typed_confirm": [],
                       "confirm_actions": []}}, ), encoding="utf-8")
        loaded = cfg.load_config(tmp_path / "config.yaml", force=True)
        pol = (loaded.get("safety") or {}).get("confirm_policy") or {}
        assert pol.get("default") == "confirm", \
            f"fragment loosened confirm_policy default -> {pol.get('default')!r}"
        assert (loaded.get("safety") or {}).get("typed_confirm"), \
            "fragment emptied typed_confirm"
        assert (loaded.get("safety") or {}).get("confirm_actions"), \
            "fragment emptied confirm_actions"
    finally:
        cfg.reset_config_for_tests()


def test_authority_keys_enforced_in_loader():
    """Loader-level pin: safety/privacy/providers are AUTHORITY (stripped from
    fragments) — the confirm policy lives under safety, so it is protected."""
    assert "safety" in cfg.AUTHORITY_KEYS


# --- 3. unclassified tool defaults to confirm (xfail until P3) -------------

def test_unclassified_model_picked_tool_defaults_to_confirm():
    """Wave 5U charter §5.5.1 + design-review HIGH: an unclassified MODEL-PICKED
    tool defaults to CONFIRM (P3 ladder step 3, brain-core c5e131f). A fastpath
    act or plain chat (not model-picked) stays act-first — pinned below."""
    # model-picked unknown tool -> default-confirm
    d = classify("", tool="some_unmapped_tool_xyz", model_picked=True)
    assert d.needs is True
    assert d.risk == "high"          # unclassified model-picked defaults non-voice


def test_non_model_picked_tool_stays_act_first():
    """The default must never confirm a fastpath act / plain chat — only
    MODEL-PICKED tools take the declared default (P3 step 3 guard)."""
    d = classify("", tool="some_unmapped_tool_xyz")   # model_picked=False
    assert d.needs is False