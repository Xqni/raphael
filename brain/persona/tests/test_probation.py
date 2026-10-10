"""Tier probation + probation-rollback tests (design 02 §2.1; lane task:
"tier probation/probation-rollback semantics"). State stays in the instance
data-dir (tmp in tests); config edits are line-scoped and comment-preserving.
"""
import json

import pytest

from brain.persona import probation as P
from brain.persona import tiers

H = 3_600_000
FRAG = ("# evolution-persona lane fragment\n"
        "persona:\n"
        "  # comment stays\n"
        "  tier: great_sage   # pinned default\n"
        "evolution:\n"
        "  mode: propose\n")


@pytest.fixture
def sp(tmp_path):
    return tmp_path / "state.json"


# ---- start ----------------------------------------------------------------
def test_start_persists_window(sp):
    st = P.start("great_sage", "raphael", {"jobs": 5, "hours": 2}, path=sp,
                 now_ms=1_000)
    assert st["status"] == "active" and st["from_tier"] == "great_sage"
    assert st["window"] == {"jobs": 5, "hours": 2}
    assert json.loads(sp.read_text(encoding="utf-8"))["to_tier"] == "raphael"
    assert P.load_state(sp)["to_tier"] == "raphael"


@pytest.mark.parametrize("frm,to", [
    ("raphael", "great_sage"),     # a demotion is a rollback, not a probation
    ("ciel", "raphael"),
    ("great_sage", "GOD"),
    ("great_sage", "great_sage"),  # no-op is not an unlock
])
def test_start_refuses_non_unlocks(frm, to, sp):
    with pytest.raises(ValueError):
        P.start(frm, to, {"jobs": 1, "hours": 1}, path=sp)


# ---- record + evaluate -----------------------------------------------------
def _active(sp, jobs=3, hours=2, now=10_000):
    return P.start("great_sage", "raphael", {"jobs": jobs, "hours": hours},
                   path=sp, now_ms=now - hours * H)


def test_ok_cycles_count_toward_window(sp):
    st = _active(sp)
    for _ in range(3):
        P.record(st, ok=True, path=sp)
    assert st["jobs_seen"] == 3
    v = P.evaluate(st, now_ms=10_000 + 3 * H, path=sp)
    assert v["status"] == "passed" and "clean" in v["reason"]
    assert P.load_state(sp)["status"] == "passed"


def test_failed_cycle_is_not_progress(sp):
    st = _active(sp, jobs=1)
    P.record(st, ok=False, reason="job failed", path=sp)
    assert st["jobs_seen"] == 0
    v = P.evaluate(st, now_ms=10_000 + 5 * H, path=sp)
    assert v["status"] == "failed" and "insufficient evidence" in v["reason"]


def test_fatal_event_fails_immediately(sp):
    st = _active(sp, jobs=50, hours=50)
    P.record(st, ok=False, reason="severity-1 regression", fatal=True, path=sp)
    assert st["status"] == "failed"
    assert "severity-1" in st["failed_reason"]
    # sticky: later clean events can't resurrect it
    P.record(st, ok=True, path=sp)
    assert P.evaluate(st, now_ms=10_000 + 100 * H, path=sp)["status"] == "failed"


def test_window_expiry_without_evidence_fails(sp):
    st = _active(sp, jobs=20, hours=2)
    P.record(st, ok=True, path=sp)
    v = P.evaluate(st, now_ms=10_000 + 10 * H, path=sp)
    assert v["status"] == "failed"
    assert "insufficient evidence" in v["reason"]


def test_active_mid_window_reports_progress(sp):
    st = _active(sp, jobs=10, hours=4)      # window ends at now=10_000
    P.record(st, ok=True, path=sp)
    v = P.evaluate(st, now_ms=10_000 - 2 * H, path=sp)   # 2h into a 4h window
    assert v["status"] == "active"
    assert "1 jobs" in v["reason"] and "10 jobs" in v["reason"]


def test_state_path_uses_instance_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("RAPHAEL_HOME", str(tmp_path))
    monkeypatch.setenv("RAPHAEL_INSTANCE", "evolution-persona")
    p = P.state_path()
    assert str(p).startswith(str(tmp_path))
    assert p.name == P.STATE_NAME
    assert "evolution-persona" in str(p)


# ---- rollback target + config application ---------------------------------
@pytest.mark.parametrize("cur,expect", [
    ("raphael", "great_sage"), ("ciel", "raphael"),
    ("great_sage", "great_sage"),
])
def test_demotion_target_one_step_down(cur, expect):
    assert P.demotion_target(cur) == expect


def test_apply_tier_preserves_everything_else():
    out = P.apply_tier(FRAG, "raphael")
    assert "  tier: raphael   # pinned default" in out
    assert "# comment stays" in out and "mode: propose" in out
    assert out.replace("  tier: raphael   # pinned default",
                       "  tier: great_sage   # pinned default") == FRAG


def test_apply_tier_roundtrip_identity():
    up = P.apply_tier(FRAG, "ciel")
    assert P.apply_tier(up, "great_sage") == FRAG


def test_apply_tier_writes_file(tmp_path):
    frag = tmp_path / "f.yaml"
    frag.write_text(FRAG, encoding="utf-8")
    P.apply_tier(FRAG, "raphael", write_to=frag)
    assert "tier: raphael" in frag.read_text(encoding="utf-8")


def test_apply_tier_refuses_missing_line_and_unknown_tier():
    with pytest.raises(ValueError):
        P.apply_tier("persona:\n  bogus: 1\n", "raphael")
    with pytest.raises(ValueError):
        P.apply_tier(FRAG, "GOD")


def test_apply_tier_on_real_lane_fragment():
    from brain import config as cfg
    real = cfg.CONFIG_PATH.parent / "config.d" / "evolution-persona.yaml"
    text = real.read_text(encoding="utf-8")
    import re as _re
    original_tier = _re.search(r"(?m)^\s*tier:\s*([a-z_]+)", text).group(1)
    out = P.apply_tier(text, "ciel")
    assert "tier: ciel" in out
    assert P.apply_tier(out, original_tier) == text   # byte-identical restore
    assert "mode: propose" in out                     # evolution block untouched


def test_demotion_is_always_allowed_rising_is_not():
    """Rollback semantics: probation failure demotes (allowed); anything that
    would raise autonomy must come from a user-approved proposal instead."""
    assert tiers.is_demotion("raphael", P.demotion_target("raphael"))
    assert not tiers.is_demotion("great_sage", P.demotion_target("great_sage"))
