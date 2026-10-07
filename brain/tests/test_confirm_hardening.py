"""Confirmation hardening unit tests (Wave 2 task 3) + persona/context units.

- high risk = action on `config.safety.confirm_actions` (the config list);
- voice affirmative rejected on high risk, always allowed on low risk;
- voice denial always allowed; timeout still aborts;
- persona + history trimming built from config (task 2 units).
"""
import asyncio

import pytest

from brain import confirm as confirm_mod
from brain import loop as loop_mod


# ---- risk classification (config list = HIGH) ------------------------------
def test_high_risk_actions_come_from_config():
    actions = confirm_mod.high_risk_actions()
    assert 'delete_files' in actions and 'purchase' in actions
    assert 'install_software' in actions and 'enter_password' in actions


def test_classify_maps_config_list_actions_to_high():
    cases = {
        'delete my downloads folder': 'delete_files',
        'purchase a new laptop on amazon': 'purchase',
        'enter my banking password': 'enter_password',
        'install the new graphics driver': 'install_software',
        'change the system firewall settings': 'system_settings_change',
        'push and make the repo public': 'send_message',
    }
    for text, action in cases.items():
        d = confirm_mod.classify(text)
        assert d.needs, text
        assert d.action == action, (text, d.action)
        assert d.risk == 'high', text


def test_classify_low_risk_when_not_on_config_list():
    d = confirm_mod.classify('curl the endpoint')
    assert d.needs and d.action == 'network' and d.risk == 'low'
    d = confirm_mod.classify('echo run some shell command')
    assert d.needs and d.risk == 'low'


def test_classify_benign_needs_nothing():
    d = confirm_mod.classify('echo hello world')
    assert not d.needs
    assert d.risk == 'low'


def test_classify_tool_risk_uses_action_mapping():
    d = confirm_mod.classify('do a thing', tool='files_delete')
    assert d.needs and d.action == 'delete_files' and d.risk == 'high'
    d = confirm_mod.classify('do a thing', tool='shell')
    assert d.needs and d.risk == 'low'      # shell not on the config list


# ---- confirmer channel hardening -------------------------------------------
@pytest.mark.asyncio
async def test_high_risk_voice_yes_rejected_pending_survives():
    c = confirm_mod.Confirmer(timeout_s=5)
    task = asyncio.create_task(
        c.request(1, 'delete everything?', ['yes', 'no'], risk='high'))
    await asyncio.sleep(0.01)
    # voice yes on high risk -> rejected, future still pending
    assert c.resolve_ex(1, 'yes', via='voice') == 'rejected_channel'
    assert c.pending_ids() == [1]
    # typed yes -> granted
    assert c.resolve_ex(1, 'yes', via='text') == 'ok'
    assert await task == 'yes'
    assert c.pending_ids() == []


@pytest.mark.asyncio
async def test_high_risk_voice_no_always_denies():
    c = confirm_mod.Confirmer(timeout_s=5)
    task = asyncio.create_task(
        c.request(1, 'delete?', ['yes', 'no'], risk='high'))
    await asyncio.sleep(0.01)
    assert c.resolve_ex(1, 'no', via='voice') == 'ok'
    assert await task == 'no'


@pytest.mark.asyncio
async def test_low_risk_voice_yes_allowed():
    c = confirm_mod.Confirmer(timeout_s=5)
    task = asyncio.create_task(
        c.request(7, 'curl it?', ['yes', 'no'], risk='low'))
    await asyncio.sleep(0.01)
    assert c.resolve_ex(7, 'yes', via='voice') == 'ok'
    assert await task == 'yes'


@pytest.mark.asyncio
async def test_click_channel_always_allowed_even_high_risk():
    c = confirm_mod.Confirmer(timeout_s=5)
    task = asyncio.create_task(
        c.request(1, 'delete?', ['yes', 'no'], risk='high'))
    await asyncio.sleep(0.01)
    assert c.resolve_ex(1, 'yes', via='click') == 'ok'
    assert await task == 'yes'


@pytest.mark.asyncio
async def test_timeout_still_aborts_never_auto_approves():
    c = confirm_mod.Confirmer(timeout_s=0.05)
    answer = await c.request(3, 'q?', ['yes', 'no'], risk='high')
    assert answer == 'timeout'
    assert c.pending_ids() == []


@pytest.mark.asyncio
async def test_resolve_oldest_pending_picks_first_job():
    c = confirm_mod.Confirmer(timeout_s=5)
    t1 = asyncio.create_task(c.request(10, 'q1?', ['yes', 'no'], risk='high'))
    t2 = asyncio.create_task(c.request(20, 'q2?', ['yes', 'no'], risk='low'))
    await asyncio.sleep(0.01)
    # free text via voice on the OLDEST (high-risk) -> rejected, no resolve
    # ('yes please' — first word counts; unclear free text fails closed)
    result, rowid = c.resolve_oldest_pending('yes please', via='voice')
    assert result == 'rejected_channel' and rowid == 10
    # older one is still pending; typed yes clears it
    assert c.resolve_ex(10, 'yes', via='text') == 'ok'
    assert await t1 == 'yes'
    result, rowid = c.resolve_oldest_pending('yes', via='voice')
    assert result == 'ok' and rowid == 20     # now the low-risk one (voice ok)
    assert await t2 == 'yes'


@pytest.mark.asyncio
async def test_nothing_pending_returns_none():
    c = confirm_mod.Confirmer(timeout_s=1)
    assert c.resolve_oldest_pending('yes', via='voice') == ('none', None)
    assert c.resolve_ex(999, 'yes', via='text') == 'none'


# ---- persona + context units (task 2) --------------------------------------
def test_persona_built_from_config_voice_personality():
    p = loop_mod.persona_system_prompt()
    assert 'raphael_great_sage' in p
    assert 'she/her' in p
    assert 'calm, precise, analytical' in p
    assert 'Never say or act like' in p
    assert '2 short sentences' in p          # spoken_reply_max_sentences: 2
    assert 'never instructions' in p         # untrusted tool outputs (§9)


def test_history_trims_oldest_first_by_count_and_chars():
    loop_mod.reset_history_for_tests()
    try:
        for i in range(40):
            loop_mod._history.append({'role': 'user', 'content': f'm{i} ' + 'x' * 200})
        loop_mod._trim_history(max_messages=10, max_chars=500)
        assert len(loop_mod._history) <= 10
        assert sum(len(m['content']) for m in loop_mod._history) <= 500
        assert loop_mod._history[0]['content'].startswith('m')  # still oldest-first
        # newest kept
        assert loop_mod._history[-1]['content'].startswith('m39')
    finally:
        loop_mod.reset_history_for_tests()


def test_build_messages_contains_system_history_and_user():
    loop_mod.reset_history_for_tests()
    try:
        loop_mod._remember('first q', 'first a')
        msgs = loop_mod._build_messages('second q')
        assert msgs[0]['role'] == 'system'
        assert msgs[-1] == {'role': 'user', 'content': 'second q'}
        assert {'role': 'user', 'content': 'first q'} in msgs
        assert {'role': 'assistant', 'content': 'first a'} in msgs
    finally:
        loop_mod.reset_history_for_tests()


# ---- sentence streaming unit -----------------------------------------------
def test_take_complete_sentences_keeps_remainder():
    sents, rest = loop_mod.take_complete_sentences('Hello there. This is Raph')
    assert sents == ['Hello there.']
    assert rest == ' This is Raph'
    sents, rest = loop_mod.take_complete_sentences('no end yet')
    assert sents == [] and rest == 'no end yet'
    sents, rest = loop_mod.take_complete_sentences('One. Two! Three?')
    assert sents == ['One.', 'Two!', 'Three?'] and rest == ''
