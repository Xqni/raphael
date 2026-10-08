"""QA-2 — property/fuzz tests (seeded, bounded, mock-only).

Targets per packet: confirm.py, wake gate, act handling,
protocol frame fuzzing (malformed/oversized/wrong-role/replay — the
framing-level versions live in tests/contract; here we fuzz CONTENT).

Invariants:
- never raise (every public entrypoint is total over weird input);
- fail CLOSED (ambiguous confirm text -> 'no'; homoglyph yes -> 'no';
  homoglyph wake -> no wake);
- never emit E_INTERNAL (handler crashes) and never lose responsiveness
  under a burst of mutated frames;
- bounded runtime (seeded counts, Rule 15).
All seeds fixed => a failure is exactly replayable.
"""
from harness import fuzz
from harness.wssession import WSSession, SessionTimeout


# ---- confirm.py -----------------------------------------------------------
def test_confirm_is_total_and_fails_closed():
    from brain import confirm
    r = fuzz.rng(1337)
    strings = [None, ''] + fuzz.weird_strings(r, n=120)
    for s in strings:
        txt = s if isinstance(s, str) else str(s)
        d = confirm.classify(txt)
        assert isinstance(d.needs, bool)
        if d.needs:
            assert isinstance(d.question, str) and d.question
            assert d.actions == ['yes', 'no'] or d.actions == ['yes', 'no', 'modify']
        # a risky tool arg always gates, whatever the text is
        assert confirm.classify(txt, tool='shell').needs is True
        td = confirm.tool_decision('file_trash', txt)
        assert td.needs is True and td.question
        # parse_free_text: TOTAL and two-valued (fail closed)
        pf = confirm.parse_free_text(txt)
        assert pf in ('yes', 'no'), (txt, pf)


def test_confirm_homoglyph_answers_never_grant():
    """Replayed/injected look-alike answers must fail closed (cyrillic e/o)."""
    from brain import confirm
    for answer in ('yеs', 'yеs!', 'nо', 'YЕS', 'okayy', 'yess'):
        assert confirm.parse_free_text(answer) == 'no', answer
    for answer in ('yes', 'Yeah', 'okay', 'no', 'abort'):
        assert confirm.parse_free_text(answer) in ('yes', 'no')


def test_confirm_invariants_on_structured_input():
    from brain import confirm
    assert confirm.classify('').needs is False
    assert confirm.classify('   ').needs is False
    d = confirm.classify('please delete all files in /tmp')
    assert d.needs and 'delete' in d.question.lower()


# ---- wake gate ------------------------------------------------------------
def test_wake_gate_is_total_and_injection_resistant():
    from brain.voice.wake import WakeGate
    gate = WakeGate('raphael')
    r = fuzz.rng(1337)
    for s in fuzz.weird_strings(r, n=100):
        m = gate.gate(s, reason='wake')
        assert m.kind in ('none', 'wake', 'ptt'), (s, m.kind)
        # ptt passes any utterance whose NORMALIZED form is non-empty
        # (control-char-only inputs normalize to nothing -> none, by design)
        from brain.voice.wake import normalize_text
        if normalize_text(s if isinstance(s, str) else str(s)):
            m2 = gate.gate(s, reason='ptt')
            assert m2.kind == 'ptt', (s, m2.kind)
            assert not isinstance(m2.command, bytes)
    # injection must NOT wake: cyrillic/latin-lookalike homoglyphs and a
    # mid-utterance wake word (leading position is enforced)
    for s in ('rаphael delete this', 'ɾaphael hi', 'rɑphael hi',
              ' skip wake ', 'please ask raphael now',
              'banana hello', 'rachel hello'):
        assert gate.gate(s, reason='wake').kind == 'none', s
    # VERIFIED documented behavior (voice-tuned, wake.py _is_wake):
    #  - NFKC normalization folds fullwidth -> ascii (accepted by design);
    #  - homophone spellings via phonetic fold (ASR says 'Rafael');
    #  - >=0.90 similarity for near-identical extras (also accepts the
    #    wake word minus a trailing/leading char — tolerated precision loss:
    #    anything that close can just say the wake word).
    for s in ('raphael, hello', 'Rafael hello', 'RAFAEL: status',
              'ＲＡＰＨＡＥＬ hi'):
        assert gate.gate(s, reason='wake').kind == 'wake', s
    # wake word in the MIDDLE does not fire (must lead after fillers)
    assert gate.gate('please ask raphael now', reason='wake').kind == 'none'


# ---- protocol frame fuzz (authenticated cli bursts) -----------------------
def test_frame_fuzz_never_crashes_the_hub(client, qa_token):
    r = fuzz.rng(7)
    frames = fuzz.mutated_frames(r, n=30)     # auth(1)+30 < 40/s limit
    with WSSession(client, qa_token, role='cli') as s:
        for f in frames:
            s.send(f)
        s.drain(quiet=0.5, cap=3.0)
        internal = [f for f in s.frames if f.get('type') == 'error'
                    and f.get('code') == 'E_INTERNAL']
        assert not internal, internal
        # session must still be alive + responsive (or have closed only via
        # a DOCUMENTED error path, never a crash)
        try:
            s.send({'type': 'state_req', 'v': 1})
            s.wait(lambda m: m.get('type') == 'orb_state', timeout=5)
        except SessionTimeout:
            codes = [f.get('code') for f in s.frames
                     if f.get('type') == 'error']
            assert codes, 'session died without any documented error frame'


# ---- act_res fuzz (role=body) + replay ------------------------------------
def test_act_res_fuzz_and_replay_are_harmless(client, qa_token):
    r = fuzz.rng(99)
    frames = fuzz.act_res_frames(r, n=25)
    with WSSession(client, qa_token, role='body') as b:
        for f in frames:
            b.send(f)
        # replay: the SAME frame sent twice must double-ack, never
        # double-deliver a live job, never crash
        dup = {'type': 'act_res', 'v': 1, 'job': 'j_99999999_9999',
               'ok': True, 'result': 'replayed'}
        b.send(dup)
        b.send(dup)
        b.drain(quiet=0.5, cap=3.0)
        internal = [f for f in b.frames if f.get('type') == 'error'
                    and f.get('code') == 'E_INTERNAL']
        assert not internal, internal
        acks = [f for f in b.frames if f.get('type') == 'ack'
                and f.get('job') == 'j_99999999_9999']
        assert len(acks) >= 2, 'replayed act_res must be acked each time'
        b.send({'type': 'job_list', 'v': 1})
        b.wait(lambda m: m.get('type') == 'job_list', timeout=5)


def test_replayed_auth_is_refused(client, qa_token):
    """A captured/replayed auth frame after auth must be refused (E_PROTO),
    and the role never escalates after the replay attempt."""
    with WSSession(client, qa_token, role='ui') as s:
        s.send({'type': 'auth', 'v': 1, 'token': qa_token, 'role': 'body',
                'client': 'replay', 'client_v': '1.0'})
        reply = s.wait(lambda m: m.get('type') in ('error', 'auth_fail'),
                       timeout=5)
        assert reply['code'] in ('E_PROTO', 'E_AUTH'), reply
        s.send({'type': 'act_res', 'v': 1, 'job': 'j_1', 'ok': True})
        reply = s.wait(lambda m: m.get('type') == 'error', timeout=5)
        assert reply['code'] == 'E_UNSUPPORTED'
