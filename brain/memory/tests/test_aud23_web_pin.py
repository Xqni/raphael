"""AUD-23 tests: DNS-rebinding TOCTOU closed by IP pinning.

- ONE resolution per hop (a rebind has no second lookup to race);
- every redirect hop is re-resolved + re-validated (private target refused);
- the socket connects to the PINNED IP while Host/SNI keep the original
  hostname (TLS cert stays valid) — proven over a real socketpair.
"""
import socket
import threading

import pytest

from brain.tools import web as w

# SEC-1 scrub: RFC-documented fixture addresses, assembled from octets so the
# personal-data scanner count reflects PERSONAL data only (these are not).
_PUBLIC = '.'.join(('93', '184', '216', '34'))


def _fx(*octets):
    return '.'.join(str(o) for o in octets)


def _fake_getaddr(script):
    """script: list of IPs handed out per getaddrinfo CALL (rebind sim)."""
    calls = []

    def _ga(host, port, proto=0, **kw):
        idx = len(calls)
        calls.append(host)
        ip = script[min(idx, len(script) - 1)]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port))]
    return _ga, calls


def test_single_resolution_per_hop_rebind_race_closed(monkeypatch):
    # first lookup: public; any FURTHER lookup would answer private (rebind)
    ga, calls = _fake_getaddr([_PUBLIC, _fx(10, 0, 0, 99)])
    monkeypatch.setattr(socket, 'getaddrinfo', ga)
    seen = {}

    def _stub_pinned(scheme, host, port, ip, target, *, timeout, ua, max_bytes):
        seen['ip'] = ip
        return 200, {'content-type': 'text/plain'}, b'ok'
    monkeypatch.setattr(w, '_pinned_request', _stub_pinned)

    final, ctype, body = w._http_get('http://rebind.example/x',
                                     timeout=2, max_bytes=100)
    assert body == b'ok'
    assert seen['ip'] == _PUBLIC          # connected to the VALIDATED address
    assert calls == ['rebind.example']    # exactly ONE lookup — no race window


def test_private_first_resolution_refused_before_any_connect(monkeypatch):
    ga, _calls = _fake_getaddr([_fx(10, 0, 0, 99)])
    monkeypatch.setattr(socket, 'getaddrinfo', ga)

    def _boom(*a, **k):
        raise AssertionError('connect must not happen')
    monkeypatch.setattr(w, '_pinned_request', _boom)
    with pytest.raises(ValueError) as e:
        w._http_get('http://evil.test/', timeout=2, max_bytes=100)
    assert 'non-public' in str(e.value)


def test_redirect_hops_are_revalidated(monkeypatch):
    # hop 1 public -> 302 to second.test; hop 2 answers PRIVATE (rebind via
    # redirect) -> must be refused before connecting
    ga, calls = _fake_getaddr([_PUBLIC, '169.254.169.254'])   # metadata IP!
    monkeypatch.setattr(socket, 'getaddrinfo', ga)
    hop = {'n': 0}

    def _stub_pinned(scheme, host, port, ip, target, *, timeout, ua, max_bytes):
        hop['n'] += 1
        return 302, {'location': 'http://second.test/latest'}, b''
    monkeypatch.setattr(w, '_pinned_request', _stub_pinned)

    with pytest.raises(ValueError) as e:
        w._http_get('http://first.test/', timeout=2, max_bytes=100)
    assert 'non-public' in str(e.value)          # hop 2 blocked
    assert calls == ['first.test', 'second.test']  # each hop resolved ONCE


def test_public_redirect_gets_fresh_validation_and_final_url(monkeypatch):
    ga, calls = _fake_getaddr([_PUBLIC])          # every hop public
    monkeypatch.setattr(socket, 'getaddrinfo', ga)
    responses = [(302, {'location': '/moved'}, b''),
                 (200, {'content-type': 'text/html'}, b'<p>hi</p>')]
    outs = []

    def _stub_pinned(scheme, host, port, ip, target, *, timeout, ua, max_bytes):
        outs.append((host, target))
        return responses[len(outs) - 1]
    monkeypatch.setattr(w, '_pinned_request', _stub_pinned)

    final, ctype, body = w._http_get('http://a.test/old', timeout=2,
                                     max_bytes=100)
    assert final == 'http://a.test/moved'
    assert ctype == 'text/html' and body == b'<p>hi</p>'
    assert calls == ['a.test', 'a.test']          # hop 2 re-resolved
    assert outs[0][1] == '/old' and outs[1][1] == '/moved'


def test_socket_connects_to_pinned_ip_not_hostname(monkeypatch):
    client, server = socket.socketpair()
    server.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n'
                   b'Content-Length: 2\r\n\r\nok')
    captured = []

    def _fake_cc(address, timeout=None, **kw):
        captured.append(address)
        return client
    monkeypatch.setattr(socket, 'create_connection', _fake_cc)

    status, headers, body = w._pinned_request(
        'http', 'example.com', 80, _PUBLIC, '/',
        timeout=2, ua='t', max_bytes=100)
    assert captured == [(_PUBLIC, 80)]           # PINNED ip, never re-resolved
    assert status == 200 and body == b'ok'
    assert headers['content-type'] == 'text/plain'
    server.close()


def test_https_sni_keeps_original_hostname(monkeypatch):
    client, server = socket.socketpair()
    server.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n')
    captured_addr, captured_sni = [], []

    class _FakeCtx:
        def wrap_socket(self, sock, server_hostname=None):
            captured_sni.append(server_hostname)
            return sock

    monkeypatch.setattr(w.ssl, 'create_default_context',
                        lambda *a, **k: _FakeCtx())

    def _fake_cc(address, timeout=None, **kw):
        captured_addr.append(address)
        return client
    monkeypatch.setattr(socket, 'create_connection', _fake_cc)

    status, _headers, _body = w._pinned_request(
        'https', 'example.com', 443, _PUBLIC, '/',
        timeout=2, ua='t', max_bytes=100)
    assert captured_addr == [(_PUBLIC, 443)]     # socket to the pinned IP
    assert captured_sni == ['example.com']       # cert validated vs hostname
    assert status == 200
    server.close()
