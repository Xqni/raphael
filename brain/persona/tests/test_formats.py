"""Answer/Notice/Report format tests (design 02 §3; wave-5 goal)."""
import pytest

from brain import config as cfg
from brain.persona import formats as F


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in ("RAPHAEL_PROFILE", "RAPHAEL_INSTANCE", "RAPHAEL_PORT",
                "RAPHAEL_BIND", "RAPHAEL_LOG_LEVEL"):
        monkeypatch.delenv(var, raising=False)
    cfg.reset_config_for_tests()
    yield
    cfg.reset_config_for_tests()


LONG = ("Analysis complete. Two risks found. The first is a stale dependency "
        "in the pipeline. The second is a disk-space trend. Recommended: act "
        "on the dependency today.")


# ---- classifier ------------------------------------------------------------
@pytest.mark.parametrize("event,expected", [
    ({"kind": "question"}, "answer"),
    ({"kind": "proactive"}, "notice"),
    ({"kind": "job_done", "task_kind": "analysis"}, "report"),
    ({"kind": "job_done", "task_kind": "simulation"}, "report"),
    ({"kind": "job_done", "job_class": "digest"}, "report"),
    ({"kind": "job_done", "task_kind": "gui"}, "answer"),
    ({"kind": "job_done"}, "answer"),            # missing class -> answer
    ({"kind": "other"}, "answer"),
    ({}, "answer"),
    (None, "answer"),
])
def test_pick_format_deterministic(event, expected):
    assert F.pick_format(event) == expected


def test_report_jobs_not_in_allowlist_never_promoted_to_report():
    for cls in ("gui", "files", "web", "notice", "bogus"):
        assert F.pick_format({"kind": "job_done", "task_kind": cls}) != "report"


# ---- sentence caps ---------------------------------------------------------
def test_truncate_respects_cap():
    assert F.truncate_sentences(LONG, 2) == "Analysis complete. Two risks found."
    assert F.truncate_sentences(LONG, 1) == "Analysis complete."
    assert F.truncate_sentences(LONG, 0) == LONG
    assert F.truncate_sentences("", 2) == ""
    assert F.truncate_sentences("One-liner", 2) == "One-liner"


def test_punctuation_variants_split():
    text = "Yes! Really? Fine… ok."
    assert F.truncate_sentences(text, 2) == "Yes! Really?"


# ---- shaping ---------------------------------------------------------------
def _cfg(**vp):
    return {"voice_personality": {"spoken_reply_max_sentences": 2, **vp}}


def test_answer_shape_full_detail_on_screen():
    out = F.shape_reply(LONG, "answer", _cfg())
    assert out["format"] == "answer"
    assert out["spoken"] == "Analysis complete. Two risks found."
    assert out["screen"] == LONG                      # full detail on screen


def test_notice_spoken_is_one_sentence():
    out = F.shape_reply(LONG, "notice", _cfg())
    assert out["spoken"] == "Analysis complete."
    assert out["screen"] == LONG


def test_report_spoken_caps_but_screen_keeps_everything():
    out = F.shape_reply(LONG, "report", _cfg())
    assert out["spoken"] == "Analysis complete. Two risks found."
    assert out["screen"] == LONG


def test_private_suppresses_screen_keeps_spoken():
    out = F.shape_reply(LONG, "answer", _cfg(), private=True)
    assert out["screen"] is None
    assert out["spoken"] == "Analysis complete. Two risks found."


def test_unknown_format_degrades_to_answer():
    out = F.shape_reply(LONG, "banana", _cfg())
    assert out["format"] == "answer"
    assert out["spoken"].startswith("Analysis complete.")


def test_format_event_end_to_end():
    out = F.format_event(LONG, {"kind": "job_done", "task_kind": "analysis"},
                         _cfg())
    assert out["format"] == "report" and "screen" in out


# ---- real config integration ---------------------------------------------
def test_caps_come_from_real_voice_personality():
    c = cfg.load_config(force=True)
    cap = c["voice_personality"]["spoken_reply_max_sentences"]
    out = F.format_event(LONG, {"kind": "question"}, c)
    assert len(F.truncate_sentences(LONG, cap).split(". ")) >= 1
    assert out["spoken"] == F.truncate_sentences(LONG, cap)
    assert cap == 2                                    # current config value


def test_private_flag_on_real_config():
    c = cfg.load_config(force=True)
    out = F.format_event(LONG, {"kind": "question"}, c, private=True)
    assert out["screen"] is None and out["spoken"]
