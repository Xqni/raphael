"""Regression: the act pipeline (PROTOCOL §7) — act_req shape, fan-out to
role=body ONLY, input-lock flag propagation, act_res → job completion,
and the LLM tool-call extraction path.
"""
import pytest

from harness.mock_body import MockBody
from harness.wssession import WSSession


def test_fastpath_gui_tool_runs_via_body_act_req(client, qa_token):
    """'screenshot' intent → category=gui → act_req to body (never local)."""
    with MockBody(client, qa_token) as body, \
         WSSession(client, qa_token, role='cli') as cli, \
         WSSession(client, qa_token, role='ui') as ui:
        cli.send({'type': 'command', 'v': 1, 'text': 'take a screenshot',
                  'source': 'text'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        req = body.next_act_req(timeout=10)
        # PROTOCOL §7 act_req shape
        assert req['v'] == 1
        assert req['action'] == 'screenshot'
        assert req['args'] == {'max_px': 1280}
        assert isinstance(req['lock'], bool)
        assert isinstance(req['timeout_ms'], int) and req['timeout_ms'] > 0
        assert req['job'].startswith('j_')
        done = cli.wait(lambda m: m.get('type') == 'job_event'
                        and m.get('status') == 'done', timeout=10)
        assert 'screenshot' in done['text'].lower() or done['text'], done
        # §4: act_req must NEVER reach ui/cli — collect everything they got
        ui.drain(quiet=0.4, cap=2.0)
        cli.drain(quiet=0.3, cap=1.5)
        assert not [f for f in ui.frames if f.get('type') == 'act_req']
        assert not [f for f in cli.frames if f.get('type') == 'act_req']


# PINNED STRICT 2026-10-06 (was xfail): uia (needs_lock) reaches the Body
# from LLM plans now — act_req carries lock:true.
def test_lock_action_sets_lock_true(client, qa_token, router_to_mock):
    """uia is needs_lock → the body must receive act_req with lock:true."""
    router_to_mock.push({'tool': {'name': 'uia',
                                  'args': {'op': 'focus', 'element': {},
                                           'args': {}}}})
    with MockBody(client, qa_token) as body, \
         WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'command', 'v': 1,
                  'text': 'arrange my windows please', 'source': 'text'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        req = body.next_act_req(timeout=8)     # times out today (xfail)
        assert req['action'] == 'uia'
        assert req['lock'] is True


def test_body_failure_fails_the_job(client, qa_token):
    with MockBody(client, qa_token,
                  script=[{'ok': False, 'error': 'E_LOCK_BUSY'}]) as body, \
         WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'command', 'v': 1, 'text': 'screenshot now please',
                  'source': 'text'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        body.next_act_req(timeout=10)
        failed = cli.wait(lambda m: m.get('type') == 'job_event'
                          and m.get('status') == 'failed', timeout=10)
        assert failed['job'], failed


@pytest.mark.xfail(reason='PROTOCOL §10: E_LOCK_BUSY is retryable and must '
                   'reach the client as such; loop.py currently converts '
                   'every act failure into E_INTERNAL (request: qa-security '
                   '-> brain-core lock-busy-code)', strict=False)
def test_lock_busy_reported_as_e_lock_busy(client, qa_token):
    with MockBody(client, qa_token,
                  script=[{'ok': False, 'error': 'E_LOCK_BUSY'}]) as body, \
         WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'command', 'v': 1, 'text': 'screenshot of screen',
                  'source': 'text'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        body.next_act_req(timeout=10)
        failed = cli.wait(lambda m: m.get('type') == 'job_event'
                          and m.get('status') == 'failed', timeout=10)
        assert failed.get('error_code') == 'E_LOCK_BUSY', failed


# PINNED STRICT 2026-10-06 (was xfail): LLM tool calls now dispatch through
# the OpenAI tool_calls response path (merged router/brain-core; the embedded
# JSON regex remains a fallback only).
def test_llm_tool_call_with_args_dispatches_to_body(client, qa_token,
                                                    router_to_mock):
    router_to_mock.push({'tool': {'name': 'launch_url',
                                  'args': {'url': 'https://example.com'}}})
    with MockBody(client, qa_token) as body, \
         WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'command', 'v': 1,
                  'text': 'prepare the weekly demo site', 'source': 'text'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        req = body.next_act_req(timeout=8)     # times out today (xfail)
        assert req['action'] == 'launch_url'
        assert req['args'] == {'url': 'https://example.com'}
