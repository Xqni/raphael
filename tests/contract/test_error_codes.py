"""PROTOCOL §10 error-code catalog conformance.

1. Doc self-consistency: retryable/fatal partition covers the catalog.
2. Runtime: every code that reaches the wire (error frames, auth_fail
   codes, job_event.error_code) during a battery of failure flows must be a
   §10 code — clients parse this set.
3. Known mapping gaps are xfail tripwires with filed requests:
   provider 429 → should be E_PROVIDER_429, circuit-open → E_CIRCUIT_OPEN is
   not in §10 at all.
"""
import re
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from harness.wssession import WSSession, recv_frame, ws_auth

PROTOCOL = Path('docs/PROTOCOL.md').read_text()


def _catalog() -> set:
    m = re.search(r'## 10\. Error codes\s*\n+\s*(.+)', PROTOCOL)
    assert m, 'PROTOCOL §10 code list not found'
    return set(re.findall(r'E_[A-Z0-9_]+', m.group(1)))


def _retry_semantics():
    m = re.search(r'\*\*Retry semantics:\*\* (.+)', PROTOCOL)
    assert m, 'PROTOCOL §10 retry semantics not found'
    line = m.group(1)
    rt = re.search(r'after backoff\):\s*(.+?)\.\s*Fatal', line)
    ft = re.search(r'Fatal \(never auto-retried\):\s*(.+?)\.\s*$', line)
    assert rt and ft, f'unparseable retry semantics: {line}'
    retryable = set(re.findall(r'E_[A-Z0-9_]+', rt.group(1)))
    fatal = set(re.findall(r'E_[A-Z0-9_]+', ft.group(1)))
    return retryable, fatal


def test_catalog_present_and_partitioned():
    catalog = _catalog()
    assert len(catalog) >= 15, catalog
    retryable, fatal = _retry_semantics()
    assert retryable | fatal == catalog, (
        f'missing from retry semantics: {catalog - (retryable | fatal)}')
    assert not (retryable & fatal), f'double-classified: {retryable & fatal}'


def test_wire_codes_during_failures_are_catalog_codes(client, qa_token):
    """Drive the failure flows a real client can hit and collect every code
    that reaches the wire — all must be §10 codes."""
    observed = {}

    # 1) bad token -> auth_fail code
    with client.websocket_connect('/ws') as ws:
        reply = ws_auth(ws, 'wrong', role='cli')
        observed['auth_fail/bad-token'] = reply['code']

    # 2) unknown type -> error code
    with WSSession(client, qa_token, role='cli') as s:
        s.send({'type': 'nope', 'v': 1})
        observed['error/unknown-type'] = s.wait(
            lambda m: m.get('type') == 'error', timeout=5)['code']

    # 3) role cap violation -> error code
    with WSSession(client, qa_token, role='ui') as s:
        s.send({'type': 'act_res', 'v': 1, 'job': 'j_1', 'ok': True})
        observed['error/role-cap'] = s.wait(
            lambda m: m.get('type') == 'error', timeout=5)['code']

    # 4) provider unreachable (router disabled) -> error frame + job_event
    with WSSession(client, qa_token, role='cli') as s:
        s.send({'type': 'command', 'v': 1, 'text': 'explain recursion simply',
                'source': 'text'})
        s.wait(lambda m: m.get('type') == 'ack', timeout=5)
        err = s.wait(lambda m: m.get('type') == 'error'
                     and m.get('job'), timeout=10)
        observed['error/provider-down'] = err['code']
        done = s.wait(lambda m: m.get('type') == 'job_event'
                      and m.get('status') == 'failed'
                      and m.get('job') == err.get('job'), timeout=10)
        observed['job_event/provider-down'] = done.get('error_code')

    # 5) confirm timeout -> job_event error_code (2 s test timeout)
    with WSSession(client, qa_token, role='cli') as s:
        s.send({'type': 'command', 'v': 1,
                'text': 'delete every file in my downloads folder',
                'source': 'text'})
        s.wait(lambda m: m.get('type') == 'ack', timeout=5)
        s.wait(lambda m: m.get('type') == 'needs_confirm', timeout=5)
        ev = s.wait(lambda m: m.get('type') == 'job_event'
                    and m.get('status') == 'cancelled', timeout=10)
        observed['job_event/confirm-timeout'] = ev.get('error_code')

    # 6) cancel -> E_CANCELLED
    with WSSession(client, qa_token, role='cli') as s:
        s.send({'type': 'command', 'v': 1,
                'text': 'delete something important please',
                'source': 'text'})
        ack = s.wait(lambda m: m.get('type') == 'ack', timeout=5)
        s.wait(lambda m: m.get('type') == 'needs_confirm'
               and m.get('job') == ack['job'], timeout=5)
        s.send({'type': 'cancel', 'v': 1, 'job': ack['job'],
                'scope': 'full'})
        ev = s.wait(lambda m: m.get('type') == 'job_event'
                    and m.get('status') == 'cancelled'
                    and m.get('job') == ack['job'], timeout=8)
        observed['job_event/cancel'] = ev.get('error_code')

    catalog = _catalog()
    for where, code in observed.items():
        assert code in catalog, f'{where} emitted {code!r} not in §10 {sorted(catalog)}'


@pytest.mark.xfail(reason='provider HTTP 429 must map to §10 E_PROVIDER_429 '
                   '(retryable), not E_PROVIDER_5XX — router complete() '
                   'catches HTTPError generically (request: qa-security -> '
                   'router provider-429-mapping)', strict=False)
def test_provider_429_maps_to_e_provider_429(client, qa_token,
                                             router_to_mock):
    router_to_mock.push({'status': 429})
    with WSSession(client, qa_token, role='cli') as s:
        s.send({'type': 'command', 'v': 1, 'text': 'summarize this article',
                'source': 'text'})
        s.wait(lambda m: m.get('type') == 'ack', timeout=5)
        err = s.wait(lambda m: m.get('type') == 'error' and m.get('job'),
                     timeout=15)
        assert err['code'] == 'E_PROVIDER_429', err


@pytest.mark.xfail(reason='E_CIRCUIT_OPEN reaches clients (router llm seam) '
                   'but is missing from PROTOCOL §10 — either map it to a '
                   '§10 transient code or add it to the catalog (request: '
                   'qa-security -> router/integrator circuit-open-code)',
                   strict=False)
def test_circuit_open_code_is_catalogued(client, qa_token, router_to_mock):
    # 5 provider failures open the breaker, the 6th plan sees the open circuit
    router_to_mock.push(*[{'status': 500}] * 5)
    with WSSession(client, qa_token, role='cli') as s:
        codes = []
        for i in range(6):
            s.send({'type': 'command', 'v': 1,
                    'text': f'write a short poem about topic{i}',
                    'source': 'text'})
            s.wait(lambda m: m.get('type') == 'ack', timeout=5)
            err = s.wait(lambda m: m.get('type') == 'error'
                         and m.get('job'), timeout=15)
            codes.append(err['code'])
            s.wait(lambda m: m.get('type') == 'job_event'
                   and m.get('status') == 'failed'
                   and m.get('job') == err['job'], timeout=10)
        assert 'E_CIRCUIT_OPEN' in codes, codes
        assert 'E_CIRCUIT_OPEN' in _catalog()
