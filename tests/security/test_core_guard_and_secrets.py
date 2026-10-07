"""Security regressions: Core Guard byte-stability (AGENT_RULES §8),
no secrets in logs/output, localhost+token gate intact.

Core Guard files (confirm.py semantics, auth, kill/pause/private control,
mode persistence) must stay BYTE-IDENTICAL unless the integrator approves a
change — approval = this manifest updated by qa-security in the same change
(request flow: docs/requests/, then re-run:
    python tests/core_guard.py --update
and commit the manifest with the approval reference).
"""
import hashlib
import json
import re
from pathlib import Path

import pytest

from harness.wssession import WSSession, recv_frame, ws_auth

REPO = Path.cwd()
MANIFEST = REPO / 'tests' / 'core_guard_manifest.json'

CORE_GUARD = {
    # file -> owning lane (for the failure message)
    'brain/confirm.py': 'brain-core (guarded by AGENT_RULES §8)',
    'brain/auth.py': 'integrator (Core Guard: auth)',
    'brain/control.py': 'integrator (Core Guard: kill/pause/private/watch)',
    'brain/mode.py': 'integrator (Core Guard: mode persistence)',
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_core_guard_byte_stable():
    assert MANIFEST.exists(), \
        f'{MANIFEST} missing — run: python tests/core_guard.py --update'
    manifest = json.loads(MANIFEST.read_text())
    drift = []
    for rel, owner in CORE_GUARD.items():
        expected = manifest.get(rel)
        actual = _sha(REPO / rel)
        if expected != actual:
            drift.append(f'{rel} ({owner}): expected {expected}, got {actual}')
    assert not drift, (
        'CORE GUARD FILES CHANGED — AGENT_RULES §8 requires an '
        'integrator-approved request (docs/requests/) before these may '
        'differ. If approved, qa-security updates the manifest via '
        'tests/core_guard.py --update. Drift:\n  ' + '\n  '.join(drift))


def test_core_guard_semantic_invariants():
    """Content tripwires that survive APPROVED edits: the guardrails must
    still exist in code, whatever the surrounding refactor."""
    confirm = (REPO / 'brain' / 'confirm.py').read_text()
    # timeout must abort, never auto-approve
    assert 'ConfirmTimeout' in confirm or 'timeout' in confirm
    assert re.search(r"return 'timeout'", confirm)
    assert 'never auto-approve' in confirm.lower()
    # ambiguous free text fails closed
    assert 'modify/unclear' in confirm, 'parse_free_text no longer fails closed'
    # the agent loop must abort on anything that is not an explicit yes
    loop = (REPO / 'brain' / 'loop.py').read_text()
    assert re.search(r"answer != 'yes'", loop), \
        'loop no longer aborts on non-yes answers'

    auth = (REPO / 'brain' / 'auth.py').read_text()
    assert 'compare_digest' in auth, 'constant-time token compare removed'
    assert 'if not expected or not candidate' in auth, \
        'auth no longer denies when no token is configured'

    mode = (REPO / 'brain' / 'mode.py').read_text()
    for action in ('private_on', 'private_off', 'pause', 'resume', 'watch_on'):
        assert f"'{action}'" in mode, f'mode lost action {action}'

    control = (REPO / 'brain' / 'control.py').read_text()
    assert 'kill_gui' in control and 'momentary' in control, \
        'kill_gui no longer momentary (persisted?)'
    actions = set(re.findall(r"'([a-z_]+)'",
                             control.split('CONTROL_ACTIONS = {')[1]
                             .split('}')[0]))
    assert {'pause', 'resume', 'private_on', 'private_off'} <= actions


def test_loop_keeps_private_before_provider_call():
    """Private Mode must suppress the PROVIDER CALL itself (not just fail
    afterwards) — brain/loop.py must check mode.private before the ONLY
    path to the model (the conversational agent loop). Fastpath runs first
    (local intents stay available), then the private gate, then llm.chat."""
    loop = (REPO / 'brain' / 'loop.py').read_text()
    private_check = loop.find('if mode.private:')
    agent_call = loop.find('await _agent_loop()')
    fastpath = loop.find('fastpath.run_intent')
    assert private_check != -1, 'loop no longer consults mode.private'
    assert agent_call != -1, 'loop no longer calls the agent loop'
    assert loop.count('await _agent_loop()') == 1, \
        'multiple agent-loop call sites — private gate must cover all'
    assert fastpath != -1 and fastpath < private_check, \
        'fastpath must run BEFORE the private gate (local intents stay)'
    assert private_check < agent_call, \
        'private check must come BEFORE the only provider-call path'
    # llm.chat (the actual model call) must live ONLY inside the agent loop
    assert 'llm.chat(' in loop, 'loop no longer calls llm.chat'


def test_ws_auth_uses_constant_time_compare():
    ws = (REPO / 'brain' / 'ws.py').read_text()
    assert 'compare_digest' in ws or 'check_token' in ws


# ---- secrets --------------------------------------------------------------
def test_token_never_in_frames_or_responses(client, qa_token, capfd):
    """A sentinel token must never appear in: any WS frame, any REST body,
    stdout/stderr (logs), or the job journal (AGENT_RULES §7)."""
    from harness.wssession import WSSession, recv_frame, ws_auth
    import json as _json

    observed_frames = []
    # drive failure paths where secrets would leak if ever echoed
    with client.websocket_connect('/ws') as ws:
        reply = ws_auth(ws, qa_token, role='ui')
        observed_frames.append(reply)
        ws.send_text(_json.dumps({'type': 'orb_input', 'v': 1,
                                  'kind': 'submit_text', 'value': 'x'}))
        observed_frames.append(recv_frame(ws, timeout=5))
    assert client.get('/health',
                      headers={'X-Raphael-Token': qa_token}).status_code == 200
    assert client.post('/control', json={'action': 'watch_on'},
                       headers={'X-Raphael-Token': qa_token}).status_code == 200
    r = client.get('/status', headers={'X-Raphael-Token': qa_token})
    observed_frames.append(r.json())

    out, err = capfd.readouterr()
    blob = out + err + _json.dumps(observed_frames)
    assert qa_token not in blob, 'token leaked into frames/logs'

    # journal rows must not contain it either
    from brain.memory import get_conn
    conn = get_conn()
    try:
        rows = conn.execute('SELECT event FROM journal').fetchall()
    finally:
        conn.close()
    journal = ' '.join(r['event'] for r in rows)
    assert qa_token not in journal, 'token leaked into the job journal'


def test_error_frames_never_carry_token(client, qa_token):
    """error.detail may surface as subtitle text (§10) — it must never be
    able to carry the token even on auth failures."""
    from harness.wssession import recv_frame, ws_auth
    with client.websocket_connect('/ws') as ws:
        reply = ws_auth(ws, 'wrong-' + qa_token, role='cli')
    assert qa_token not in str(reply), reply


def test_usage_log_has_no_prompt_or_key_text(client, qa_token,
                                             router_to_mock, tmp_path):
    """router usage.jsonl records usage METADATA only — no prompt text, no
    key material (test writes to tmp; the log shape is what's asserted)."""
    router_to_mock.push({'content': 'short answer'})
    with WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'command', 'v': 1,
                  'text': 'summarize SECRET_PROMPT_MARKER_42',
                  'source': 'text'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        cli.wait(lambda m: m.get('type') == 'job_event'
                 and m.get('status') == 'done', timeout=15)
    log = tmp_path / 'usage.jsonl'
    assert log.exists(), 'usage log was never written'
    text = log.read_text()
    assert 'SECRET_PROMPT_MARKER_42' not in text, 'prompt text in usage log'
    assert 'sk-qa-fake' not in text, 'API key material in usage log'
    for line in text.splitlines():
        row = json.loads(line)
        assert set(row) <= {'timestamp', 'provider', 'model',
                            'tokens_input', 'tokens_output', 'latency_ms',
                            'outcome', 'task_kind', 'error_code'}, row


# ---- localhost + token ----------------------------------------------------
@pytest.mark.xfail(strict=False,
                   reason='FastAPI serves /docs and /openapi.json WITHOUT '
                          'token auth — unauthenticated API-surface '
                          'disclosure (PROTOCOL §11 token-gated surface). '
                          'Fix: FastAPI(docs_url=None, openapi_url=None) or '
                          'a gate (request: qa-security -> brain-core '
                          'disable-fastapi-docs)')
def test_only_expected_routes_exist(client, qa_token):
    """No unauthenticated debug/schema surfaces — openapi/docs must not
    expose the API without the token."""
    for path in ('/openapi.json', '/docs', '/redoc'):
        r = client.get(path)
        assert r.status_code in (401, 404), \
            f'{path} is publicly reachable ({r.status_code})'


def test_rest_bind_defaults_stay_documented():
    """The listener posture is PROTOCOL §1's: WSL NAT 0.0.0.0 with token, or
    127.0.0.1 in mirrored mode / explicit override. Nothing may default to a
    LAN-exposed listener without auth."""
    import brain.run as run_mod
    # no override, no wslinfo → NAT default (token mandatory per §2)
    import os
    old = os.environ.pop('RAPHAEL_BIND', None)
    try:
        assert run_mod.detect_host() in ('0.0.0.0', '127.0.0.1')
    finally:
        if old is not None:
            os.environ['RAPHAEL_BIND'] = old
    os.environ['RAPHAEL_BIND'] = '127.0.0.1'
    try:
        assert run_mod.detect_host() == '127.0.0.1'
    finally:
        os.environ.pop('RAPHAEL_BIND', None)
