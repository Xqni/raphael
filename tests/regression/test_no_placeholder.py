"""Regression: NO placeholder replies anywhere in the user-visible paths.

History: the phase-1 stub spoke '[provider:model] response' aloud
(brain/router/core.py docstring). These tests pin the real behavior: reply
text delivered to job_event / speak / subtitle is EXACTLY what the (mock)
provider or fastpath produced — no template wrappers, no empty text.
"""
from harness import voicespy
from harness.wssession import WSSession

PLACEHOLDER_MARKERS = ('[provider', '{provider', 'TODO', 'lorem ipsum',
                       'placeholder', '???', 'not implemented', 'stub')


def _assert_no_placeholders(text: str, where: str):
    low = (text or '').lower()
    for marker in PLACEHOLDER_MARKERS:
        assert marker.lower() not in low, f'{where}: placeholder {marker!r} in {text!r}'


def test_llm_reply_delivered_verbatim(client, qa_token, router_to_mock):
    mock_text = 'Dune is a 1965 novel by Frank Herbert about desert politics.'
    router_to_mock.push({'content': mock_text})
    with WSSession(client, qa_token, role='cli') as s:
        s.send({'type': 'command', 'v': 1,
                'text': 'summarize the plot of dune', 'source': 'text'})
        s.wait(lambda m: m.get('type') == 'ack', timeout=5)
        done = s.wait(lambda m: m.get('type') == 'job_event'
                      and m.get('status') == 'done', timeout=15)
        assert done['text'] == mock_text, done
        # subtitle may arrive before or after `done` — drain, then inspect
        # everything this session received
        s.drain(quiet=0.5, cap=2.0)
        subs = [f for f in s.frames if f.get('type') == 'subtitle']
        assert subs, [f.get('type') for f in s.frames]
        assert any(sub['text'] == mock_text for sub in subs), subs
    speaks = [c['text'] for c in voicespy.SPEAK_CALLS]
    assert mock_text in speaks, speaks
    for frame in s.frames:
        for key in ('text', 'detail', 'question'):
            if isinstance(frame.get(key), str):
                _assert_no_placeholders(frame[key],
                                        f"{frame.get('type')}.{key}")


def test_fastpath_reply_is_concrete(client, qa_token):
    with WSSession(client, qa_token, role='cli') as s:
        s.send({'type': 'command', 'v': 1, 'text': 'echo concrete reply',
                'source': 'text'})
        s.wait(lambda m: m.get('type') == 'ack', timeout=5)
        done = s.wait(lambda m: m.get('type') == 'job_event'
                      and m.get('status') == 'done', timeout=8)
        assert done['text'] == 'Echo: concrete reply', done
        _assert_no_placeholders(done['text'], 'fastpath done')


def test_provider_failure_reply_is_not_a_template(client, qa_token):
    """Provider-down path: the spoken line is the documented graceful
    sentence, the job error is structured — never a raw template."""
    with WSSession(client, qa_token, role='cli') as s:
        s.send({'type': 'command', 'v': 1,
                'text': 'explain orbital mechanics briefly',
                'source': 'text'})
        s.wait(lambda m: m.get('type') == 'ack', timeout=5)
        done = s.wait(lambda m: m.get('type') == 'job_event'
                      and m.get('status') == 'failed', timeout=10)
        assert done['text'], 'empty failure text'
        _assert_no_placeholders(done['text'], 'provider-down text')
    spoken = [c['text'] for c in voicespy.SPEAK_CALLS]
    assert any('model provider' in t for t in spoken), spoken
