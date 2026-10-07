"""Baseline capture/compare tests (design 01 §2.5): fail-closed promote gate."""
import json

from brain.evolution import baseline as B


def _transcript(name="open-youtube"):
    return {"name": name, "steps": [
        {"type": "fastpath", "name": "search_youtube", "target": "lo-fi"},
        {"type": "act_req", "name": "launch_url", "target": "youtube.com"},
    ]}


def _shadow(ok=True, rc=0):
    return {"ok": ok, "rc": rc, "command": "pytest -q x", "output": "42 passed"}


# ---- capture/save/load -----------------------------------------------------
def test_capture_real_repo(tmp_path):
    cap = B.capture(B.REPO_ROOT, _shadow())
    assert cap["commit"] and len(cap["commit"]) == 40
    assert cap["core_guard"]["ok"] is True          # real guard check
    assert cap["shadow"]["ok"] is True
    assert "42 passed" in cap["shadow"]["output_tail"]
    assert cap["transcripts"] == []


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "baseline.json"
    cap = B.capture(B.REPO_ROOT, _shadow())
    B.save(cap, path)
    assert B.load(path) == json.loads(path.read_text(encoding="utf-8"))
    assert B.load(tmp_path / "nope.json") is None    # missing = None, not crash


# ---- compare ---------------------------------------------------------------
def _current(**over):
    cur = B.capture(B.REPO_ROOT, _shadow(), transcripts=[_transcript()])
    cur.update(over)
    return cur


def test_identical_candidate_passes():
    base = B.capture(B.REPO_ROOT, _shadow(), transcripts=[_transcript()])
    verdict = B.compare(_current(), base)
    assert verdict["ok"] is True and verdict["deltas"] == []


def test_missing_baseline_fails_closed():
    verdict = B.compare(_current(), None)
    assert verdict["ok"] is False


def test_shadow_failure_fails_promote():
    base = B.capture(B.REPO_ROOT, _shadow(), transcripts=[_transcript()])
    verdict = B.compare(_current(shadow=_shadow(ok=False, rc=1)), base)
    assert verdict["ok"] is False
    assert any("shadow run failed" in d for d in verdict["deltas"])


def test_core_guard_flip_fails_promote():
    base = B.capture(B.REPO_ROOT, _shadow())
    cur = _current()
    cur["core_guard"] = {"ok": False, "msg": "drift"}
    verdict = B.compare(cur, base)
    assert verdict["ok"] is False
    assert any("core guard NOT ok" in d for d in verdict["deltas"])


def test_commit_move_alone_is_not_failure():
    """A candidate patch moves HEAD — that alone must not block promote."""
    base = B.capture(B.REPO_ROOT, _shadow(), transcripts=[_transcript()])
    cur = _current(commit="0" * 40)
    verdict = B.compare(cur, base)
    assert verdict["ok"] is True
    assert any(d.startswith("commit moved") for d in verdict["deltas"])


# ---- transcripts -----------------------------------------------------------
def test_transcript_step_change_is_delta():
    expected = _transcript()["steps"]
    actual = [
        {"type": "fastpath", "name": "search_youtube", "target": "lo-fi"},
        {"type": "act_req", "name": "open_app", "target": "notepad"},
    ]
    diffs = B.compare_transcripts(expected, actual)
    assert len(diffs) == 1 and "launch_url" in diffs[0] and "open_app" in diffs[0]


def test_transcript_extra_and_missing_steps():
    expected = _transcript()["steps"]
    assert any("extra step" in d for d in B.compare_transcripts(expected, expected[:-1]))
    assert any("extra step" in d for d in B.compare_transcripts(expected[:-1], expected))
    assert B.compare_transcripts(expected, expected) == []


def test_transcript_delta_blocks_promote():
    base = B.capture(B.REPO_ROOT, _shadow(), transcripts=[_transcript()])
    changed = _transcript()
    changed["steps"][1] = {"type": "act_req", "name": "open_app", "target": "notepad"}
    verdict = B.compare(_current(transcripts=[changed]), base)
    assert verdict["ok"] is False
    assert any("open-youtube" in d for d in verdict["deltas"])
