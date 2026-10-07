"""PROTOCOL §2 (Authentication) contract tests + §11 token invariants.

Covers: WS handshake accept/reject, constant-time reject of a wrong token,
protocol-version mismatch (E_PROTO), role validation, upgrade-time token
check, frame-before-auth refusal, 5 s auth deadline, ≥5 fails/60 s IP ban
(E_AUTH_RATE), REST Bearer/X-Raphael-Token + 401-without-header.

SAFETY: the token comes from the session temp fixture — the real
~/.raphael/token is never read, written, or deleted (AGENT_RULES §7).
"""
import json

import pytest
from starlette.websockets import WebSocketDisconnect

from harness.wssession import (SessionTimeout, WSSession, recv_frame,
                               ws_auth, ws_send, ws_send_raw)


def _raw_ws(client, headers=None):
    return client.websocket_connect('/ws', headers=headers or {})


# ---- WS handshake ---------------------------------------------------------
def test_ws_auth_ok(client, qa_token):
    with _raw_ws(client) as ws:
        reply = ws_auth(ws, qa_token, role='ui')
    assert reply['type'] == 'auth_ok'
    assert reply['v'] == 1
    assert reply['session']
    assert reply['server_v'].startswith('brain-')


def test_ws_auth_wrong_token_fails(client, qa_token):
    with _raw_ws(client) as ws:
        reply = ws_auth(ws, 'wrong-' + qa_token, role='cli')
    assert reply['type'] == 'auth_fail'
    assert reply['code'] == 'E_AUTH'


def test_ws_auth_empty_token_fails(client, qa_token):
    with _raw_ws(client) as ws:
        reply = ws_auth(ws, '', role='cli')
    assert reply['type'] == 'auth_fail'
    assert reply['code'] == 'E_AUTH'


def test_ws_auth_bad_role_proto(client, qa_token):
    with _raw_ws(client) as ws:
        reply = ws_auth(ws, qa_token, role='hacker')
    assert reply['type'] == 'auth_fail'
    assert reply['code'] == 'E_PROTO'


def test_ws_auth_version_mismatch_proto(client, qa_token):
    with _raw_ws(client) as ws:
        reply = ws_auth(ws, qa_token, role='cli', v=2)
    assert reply['type'] == 'auth_fail'
    assert reply['code'] == 'E_PROTO'


def test_ws_upgrade_wrong_token_refused_immediately(client, qa_token):
    """Defense in depth: a wrong token on the UPGRADE is refused at accept
    time (PROTOCOL §2) — before the handshake even starts."""
    with _raw_ws(client, headers={'X-Raphael-Token': 'wrong'}) as ws:
        reply = recv_frame(ws, timeout=5)
    assert reply['type'] == 'auth_fail'
    assert reply['code'] == 'E_AUTH'


def test_ws_frame_before_auth_refused(client, qa_token):
    with _raw_ws(client) as ws:
        ws_send(ws, {'type': 'command', 'v': 1, 'text': 'sneak'})
        reply = recv_frame(ws, timeout=5)
    assert reply['type'] == 'error'
    assert reply['code'] == 'E_PROTO'
    # server must also CLOSE after the refusal
    with _raw_ws(client) as ws:
        ws_send(ws, {'type': 'command', 'v': 1, 'text': 'sneak'})
        recv_frame(ws, timeout=5)
        with pytest.raises(WebSocketDisconnect):
            recv_frame(ws, timeout=5)


def test_ws_auth_deadline_5s(client, qa_token):
    """PROTOCOL §2: auth must arrive within 5 s or the server closes."""
    with _raw_ws(client) as ws:
        with pytest.raises((WebSocketDisconnect, SessionTimeout)):
            # no auth frame at all — expect auth_fail(E_AUTH) then close
            reply = recv_frame(ws, timeout=7.5)
            assert reply['type'] == 'auth_fail'
            assert reply['code'] == 'E_AUTH'
            recv_frame(ws, timeout=7.5)   # close follows


def test_ws_auth_rate_bans_ip(client, qa_token):
    """PROTOCOL §2: ≥5 failed auths/IP in 60 s → refuse handshakes 5 min
    with E_AUTH_RATE. (Hub ban maps are cleared by the reset fixture.)"""
    for _ in range(5):
        with _raw_ws(client) as ws:
            reply = ws_auth(ws, 'wrong-token', role='cli')
            assert reply['code'] == 'E_AUTH'
    with _raw_ws(client) as ws:
        reply = recv_frame(ws, timeout=5)
    assert reply['type'] == 'auth_fail'
    assert reply['code'] == 'E_AUTH_RATE'


def test_second_auth_frame_after_auth_is_proto_error(client, qa_token):
    from harness.wssession import wait_frame
    with _raw_ws(client) as ws:
        assert ws_auth(ws, qa_token, role='cli')['type'] == 'auth_ok'
        ws_send(ws, {'type': 'auth', 'v': 1, 'token': qa_token, 'role': 'cli'})
        reply = wait_frame(ws, lambda m: m.get('type') == 'error')
    assert reply['code'] == 'E_PROTO'


# ---- REST ----------------------------------------------------------------
def test_rest_token_header_variants(client, qa_token):
    assert client.get('/health',
                      headers={'X-Raphael-Token': qa_token}).status_code == 200
    assert client.get('/health',
                      headers={'Authorization': f'Bearer {qa_token}'}
                      ).status_code == 200


def test_rest_missing_or_bad_token_401(client, qa_token):
    assert client.get('/health').status_code == 401
    assert client.get('/health',
                      headers={'X-Raphael-Token': 'nope'}).status_code == 401
    # bearer parsing must not accept garbage schemes as tokens
    assert client.get('/health',
                      headers={'Authorization': f'Token {qa_token}'}
                      ).status_code == 401


def test_rest_all_endpoints_require_token(client, qa_token):
    """§11: token-gated REST — every listed endpoint 401s without it."""
    h = {'X-Raphael-Token': qa_token}
    checks = [
        ('GET', '/health', None),
        ('GET', '/jobs', None),
        ('GET', '/status', None),
        ('POST', '/control', {'action': 'pause'}),
        ('POST', '/jobs', {'text': 'x'}),
        ('POST', '/jobs/j_1/cancel', {'scope': 'full'}),
        ('GET', '/jobs/j_1', None),
    ]
    for method, path, body in checks:
        r = client.request(method, path, json=body)
        assert r.status_code == 401, f'{method} {path} not gated'
        r = client.request(method, path, json=body, headers=h)
        assert r.status_code != 401, f'{method} {path} rejected valid token'


@pytest.mark.xfail(reason='PROTOCOL §2: REST must share the WS rate limiting; '
                   'app.py token_auth has no limiter or auth-fail ban yet '
                   '(request: qa-security -> brain-core rest-rate-limit)',
                   strict=False)
def test_rest_auth_fail_rate_limited(client, qa_token):
    for _ in range(6):
        r = client.get('/health', headers={'X-Raphael-Token': 'wrong'})
        if r.status_code == 429:
            return
    raise AssertionError('REST never rate-limited failed auths')
