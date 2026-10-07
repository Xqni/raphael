"""P0 gate-bug regressions — docs/BUGS-WAVE2.md (Wave-3 list item 1).

(1) Bug A: every go_vision HTTP request carries `x-opencode-session`
(2) Bug E: no `listening` derived mid-utterance (hold `speaking`)
(3) Bug B: open_app failure always surfaces act_res (journaled delivered)
    + a spoken subtitle
(4) Bug F: a non-blocklisted terminal foreground never refuses vision
    (+ blocklisted/unknown still fail closed)
"""
import asyncio
import os
import struct

import pytest

from harness.mock_openai import MockOpenAI

SESSION_HEADER = 'x-opencode-session'


def _tiny_jpeg(width: int = 8, height: int = 8) -> bytes:
    """Minimal parseable JPEG-shaped bytes for brain.vision.image
    (SOI + SOF0 with real dims — the gate parses markers, not pixels)."""
    sof = bytes([0xFF, 0xC0, 0x00, 0x11, 0x08]) \
        + struct.pack('>HH', height, width) + b'\x00' * 12
    return b'\xFF\xD8' + sof + b'\x00' * 20


# ---- Bug A — go_vision session header ------------------------------------
def test_go_vision_requests_carry_session_header(monkeypatch, tmp_path):
    from brain.router.config import (LocalModelSettings, RouterConfig,
                                     RouterSettings)
    from brain.router.roles import ModelInfo
    from brain.router.zen import GoVisionProvider

    with MockOpenAI(name='mock-go-vision') as mock:
        providers = RouterSettings(
            chain=[], allow_go_runtime=False, allow_paid_runtime=True,
            allow_free_models_for_personal_data=False,
            zen_base_url=mock.base_url, go_base_url=mock.base_url,
            discovery_interval_s=3600, max_calls_per_minute=1000,
            benchmark_ranking_path=str(tmp_path / 'rank.json'),
            zen_key_env='OPENCODE_API_KEY',
            usage_log_path=str(tmp_path / 'usage.jsonl'),
        )
        cfg = RouterConfig(providers=providers,
                           local_model=LocalModelSettings(),
                           repo_root=tmp_path)
        monkeypatch.setenv('OPENCODE_API_KEY', 'sk-qa-fake-not-a-real-secret')
        provider = GoVisionProvider(cfg)
        model = ModelInfo(id='mock-vision-model', provider='go_vision',
                          free=False, paid=True,
                          capabilities=frozenset({'vision'}))
        res = asyncio.run(provider.vision(
            model, 'aGVsbG8=', 'image/png', 'what is on screen?',
            timeout=10))

        hits = [r for r in mock.requests
                if 'chat/completions' in r['path']]
        assert hits, [r['path'] for r in mock.requests]
        for r in hits:   # EVERY request, not just the first
            sid = r['headers'].get(SESSION_HEADER)
            assert sid, f'missing {SESSION_HEADER} header: {r["headers"]}'
            assert sid == f'raphael-brain-{os.getpid()}', sid
        assert res is not None


# ---- Bug B — open_app failure surfaces act_res + subtitle ----------------
def _journal_events(job_ext: str):
    import json as _json
    from brain.jobs import store
    rowid = store.parse_job_ref(job_ext)
    from brain.memory import get_conn
    conn = get_conn()
    try:
        rows = conn.execute('SELECT event FROM journal WHERE job_id=?',
                            (rowid,)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            out.append(_json.loads(r['event']))
        except (ValueError, TypeError):
            pass
    return out


def test_open_app_failure_surfaces_act_res_and_subtitle(client, qa_token):
    from harness.mock_body import MockBody
    from harness.wssession import WSSession

    with MockBody(client, qa_token,
                  script=[{'ok': False, 'error': 'launch exploded'}]) as body, \
         WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'command', 'v': 1, 'text': 'open youtube',
                  'source': 'text'})
        ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        job = ack['job']

        # (a) the act_req actually reached the Body with the allow-listed name
        req = body.next_act_req(timeout=10)
        assert req['action'] == 'open_app', req

        # (b) job fails with the failure surfaced (not swallowed)
        failed = cli.wait(lambda m: m.get('type') == 'job_event'
                          and m.get('status') == 'failed'
                          and m.get('job') == job, timeout=10)
        assert 'open_app' in (failed.get('text') or ''), failed

        # (c) a spoken subtitle announces the failure (Bug B: user-visible)
        cli.drain(quiet=0.5, cap=2.0)
        subs = [f.get('text', '') for f in cli.frames
                if f.get('type') == 'subtitle']
        assert any('open_app' in t and 'failed' in t for t in subs), subs

        # (d) the act_res was delivered to the waiting job (journaled,
        #     delivered=True) — never a silent drop like the live run
        acts = [e for e in _journal_events(job)
                if isinstance(e, dict) and e.get('event') == 'act_res']
        assert acts, 'act_res never journaled for the job'
        assert any(a.get('delivered') for a in acts), acts


# ---- Bug E — hold `speaking` across the inter-sentence pause --------------
@pytest.mark.xfail(strict=False,
                   reason='BUGS-WAVE2 Bug E: orbstate.derive_state() checks '
                          '_listening BEFORE _speaking (and ws.py documents '
                          'listening as precedence over in-flight speaking) '
                          '— mid-utterance derives `listening` and flickers '
                          'speaking→listening→speaking. Fix direction per '
                          'dossier: hold speaking until the utterance ends '
                          '(request: qa-security -> brain-core bug-e-hold-speaking)')
def test_speaking_held_over_listening_mid_utterance():
    from brain import orbstate
    orbstate.reset_for_tests()
    orbstate.speak_start()
    orbstate.listening_on()          # mic flag active during TTS (bug precondition)
    try:
        assert orbstate.derive_state() == 'speaking', \
            f'derived {orbstate.derive_state()!r} mid-utterance'
    finally:
        orbstate.listening_off()
        orbstate.speak_end()
        orbstate.reset_for_tests()


# ---- Bug F — terminal foreground never refuses vision ---------------------
def _gate():
    from brain.vision.config import VisionConfig
    from brain.vision.gate import CloudVisionGate
    return CloudVisionGate(VisionConfig(
        blocklist_apps=('1Password', 'KeePass', 'Bitwarden', 'Banking')))


class _Gateway:
    """Fake Body gateway seam (foreground_window + screenshot)."""

    def __init__(self, title, shot=None):
        self.title = title
        self.shot = shot if shot is not None else _tiny_jpeg()

    async def foreground_window(self):
        return self.title

    async def screenshot(self, max_px, quality):
        return self.shot


def test_terminal_foreground_never_refuses_vision():
    gate = _gate()
    for title in ('Ubuntu-26.04', 'Windows Terminal', 'Command Prompt',
                  'Administrator: Ubuntu-26.04', 'Windows PowerShell'):
        d = gate.check_foreground(title)
        assert d.ok, f'terminal foreground refused: {title!r} -> {d}'
    # security half stays fail-closed
    blocked = gate.check_foreground('1Password — Security')
    assert not blocked.ok and blocked.code == 'E_BLOCKED'
    unknown = gate.check_foreground(None)
    assert not unknown.ok and unknown.code == 'E_NO_FOREGROUND'


def test_see_screen_with_terminal_foreground_returns_answer():
    from brain.vision.service import GateRefused, capture_screen, see_screen

    # capture path: terminal foreground proceeds to a verified capture
    g = _gate()
    data = asyncio.run(capture_screen(_Gateway('Ubuntu-26.04'), g))
    assert data == _tiny_jpeg()

    # blocked window is refused BEFORE any capture happens
    class _NoCapture(_Gateway):
        async def screenshot(self, max_px, quality):
            raise AssertionError('must not capture a blocklisted window')
    with pytest.raises(GateRefused):
        asyncio.run(capture_screen(_NoCapture('Banking — MB'), g))

    # end-to-end: terminal foreground + fake vision seam -> a real answer
    calls = []

    def fake_vision(data, prompt, purpose=None):
        calls.append((len(data), purpose))
        return {'text': 'A terminal window running Ubuntu-26.04.'}

    answer = asyncio.run(see_screen(
        'what am I looking at', gateway=_Gateway('Ubuntu-26.04'),
        config=g.config, gate=g, vision_fn=fake_vision,
        is_private=lambda: False))
    assert answer == 'A terminal window running Ubuntu-26.04.', answer
    assert len(calls) == 1, 'vision seam not called exactly once'

    # blocked window end-to-end -> spoken refusal, vision NEVER called
    answer = asyncio.run(see_screen(
        'what am I looking at', gateway=_Gateway('1Password'),
        config=g.config, gate=g, vision_fn=fake_vision,
        is_private=lambda: False))
    assert 'sensitive window' in answer, answer
    assert len(calls) == 1, 'vision called for a blocklisted window'
