"""Wave 2 task 4 — voice confirmation parsing (yes/no/modify) for LOW-risk
confirmations; high-risk confirmations are non-voice (fail-closed, Core Guard
semantics stay in brain/confirm.py — AGENT_RULES §8, this module only asks the
caller to pass `low_risk` in).

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from brain.voice import (parse_voice_answer, to_confirm_answer,  # noqa: E402
                         voice_confirmation_answer)


@pytest.mark.parametrize("text,kind", [
    ("yes", "yes"),
    ("Yeah.", "yes"),
    ("sure", "yes"),
    ("okay", "yes"),
    ("uh huh", "yes"),
    ("confirmed", "yes"),
    ("no", "no"),
    ("nah", "no"),
    ("stop", "no"),
    ("cancel", "no"),
    ("don't", "no"),
    ("yes, but only the PDFs", "modify"),
    ("no, wait — make it five files", "modify"),
    ("change it to tomorrow instead", "modify"),
    ("not quite", "modify"),
    ("what time is it", "unrecognized"),
    ("open youtube", "unrecognized"),
    ("", "unrecognized"),
    ("   ", "unrecognized"),
])
def test_parse_voice_answer(text, kind):
    a = parse_voice_answer(text)
    assert a.kind == kind, f"{text!r} -> {a.kind}"


def test_answer_properties():
    a = parse_voice_answer("yes")
    assert a.definitive and bool(a)
    assert not parse_voice_answer("hmm").definitive
    assert not bool(parse_voice_answer("hmm"))
    assert parse_voice_answer("Yes, go ahead.").raw == "Yes, go ahead."


def test_low_risk_yes_proceeds_no_and_modify_fail_closed():
    assert to_confirm_answer(parse_voice_answer("yes"), low_risk=True) == "yes"
    assert to_confirm_answer(parse_voice_answer("no"), low_risk=True) == "no"
    # conditional -> abort + re-ask (never a silent approval, addendum §7)
    assert to_confirm_answer(parse_voice_answer("yes, but only the PDFs"),
                             low_risk=True) == "no"
    # unclear -> keep waiting (caller timeout still ABORTS; never auto-approve)
    assert to_confirm_answer(parse_voice_answer("hmm"), low_risk=True) is None


def test_high_risk_confirmation_is_never_voice():
    """The Core Guard requirement: for HIGH-risk confirmations voice is not an
    accepted channel — even an unambiguous 'yes' resolves to None."""
    for text in ("yes", "sure, go ahead", "approved", "yep"):
        assert to_confirm_answer(parse_voice_answer(text),
                                 low_risk=False) is None


def test_one_call_helper():
    assert voice_confirmation_answer("yes", low_risk=True) == "yes"
    assert voice_confirmation_answer("yes", low_risk=False) is None
    assert voice_confirmation_answer("whatever", low_risk=True) is None


def test_vocabulary_stays_in_sync_with_core_guard():
    """Seeded from brain/confirm.py so spoken and typed answers agree."""
    confirm = pytest.importorskip("brain.confirm")
    for word in ("go", "proceed", "aborted", "denied"):
        a = parse_voice_answer(word)
        assert a.kind in ("yes", "no"), f"{word} -> {a.kind}"
    # typed and voice paths agree on the same words
    from brain.confirm import parse_free_text
    for word in ("yes", "okay", "no", "cancel"):
        typed = parse_free_text(word)
        voiced = to_confirm_answer(parse_voice_answer(word), low_risk=True)
        assert voiced == typed, f"{word}: voice={voiced} typed={typed}"
