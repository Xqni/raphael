"""Tier behavior tests (design 02 §2/§2.1): deny-by-default autonomy zones +
unlock criteria are evaluated, never applied."""
import pytest

from brain.persona import tiers

ALL_TIERS = tiers.TIERS


# ---- autonomy zones --------------------------------------------------------
def test_great_sage_proposes_only():
    cfg = {"persona": {"tier": "great_sage"}}
    assert tiers.zone_of(cfg) == frozenset()
    for cls in ("notice", "reminder", "status_check", "memory_maintenance"):
        assert not tiers.can_start_proactive(cfg, cls)


def test_raphael_small_safe_zone():
    cfg = {"persona": {"tier": "raphael"}}
    for cls in ("notice", "reminder", "status_check", "memory_maintenance"):
        assert tiers.can_start_proactive(cfg, cls)
    # not yet earned by raphael:
    assert not tiers.can_start_proactive(cfg, "file_analysis")
    assert not tiers.can_start_proactive(cfg, "web_research")


def test_ciel_broader_earned_zone():
    cfg = {"persona": {"tier": "ciel"}}
    for cls in ("file_analysis", "web_research", "digest", "schedule_scan",
                "summarize"):
        assert tiers.can_start_proactive(cfg, cls)
    # raphael's zone is a subset:
    for cls in tiers.PROACTIVE_ZONE["raphael"]:
        assert tiers.can_start_proactive(cfg, cls)


def test_authority_classes_never_allowed_at_any_tier():
    forbidden = {"shell_write", "purchase", "send_message", "delete",
                 "publish_public", "spend", "secrets", "install",
                 "system_settings", "make_public_repo"}
    union = set().union(*tiers.PROACTIVE_ZONE.values())
    assert not (union & forbidden), union & forbidden


def test_unknown_class_denied_everywhere():
    for t in ALL_TIERS:
        cfg = {"persona": {"tier": t}}
        assert not tiers.can_start_proactive(cfg, "totally_new_class")


def test_zone_fails_closed_on_bogus_tier():
    for bogus in ({"persona": {"tier": "GOD"}}, {}, {"persona": {}}):
        assert tiers.tier_of(bogus) == "great_sage"
        assert tiers.zone_of(bogus) == frozenset()
        assert not tiers.can_start_proactive(bogus, "notice")


# ---- demotion guard --------------------------------------------------------
@pytest.mark.parametrize("cur,new,expect", [
    ("raphael", "great_sage", True),
    ("ciel", "raphael", True),
    ("ciel", "great_sage", True),
    ("great_sage", "raphael", False),     # raising autonomy: never automatic
    ("raphael", "ciel", False),
    ("ciel", "ciel", False),
    ("GOD", "great_sage", False),
    ("great_sage", "nope", False),
])
def test_is_demotion_only_lowers(cur, new, expect):
    assert tiers.is_demotion(cur, new) is expect


# ---- unlock criteria (evaluated, never applied) ---------------------------
def _raphael_stats(**over):
    s = {"days_since_sev1": 10, "tests_green": True, "job_success_rate": 0.98,
         "confirm_timeouts": 0, "user_approval": False}
    s.update(over)
    return s


def test_raphael_eligible_but_never_auto_approved():
    res = tiers.evaluate_unlock(_raphael_stats(), "raphael")
    assert res["ready"] is True                 # eligible for a PROPOSAL
    assert res["unmet"] == ["user approval"]    # but not self-granted
    assert "7+ days since last severity-1 failure" in res["met"]


def test_raphael_with_approval_fully_met():
    res = tiers.evaluate_unlock(_raphael_stats(user_approval=True), "raphael")
    assert res["unmet"] == [] and res["ready"] is True


@pytest.mark.parametrize("broken", [
    {"days_since_sev1": 3}, {"tests_green": False},
    {"job_success_rate": 0.80}, {"confirm_timeouts": 2},
])
def test_raphael_blocked_when_any_criterion_fails(broken):
    res = tiers.evaluate_unlock(_raphael_stats(**broken), "raphael")
    assert res["ready"] is False and res["unmet"]


def test_ciel_requires_stability_clean_probations_no_rollbacks():
    good = {"days_stable": 35, "failed_probations": 0, "rollbacks": 0,
            "user_approval": True}
    res = tiers.evaluate_unlock(dict(good), "ciel")
    assert res["ready"] is True and res["unmet"] == []
    for broken in ({"days_stable": 10}, {"failed_probations": 1},
                   {"rollbacks": 1}):
        stats = dict(good); stats.update(broken)
        r = tiers.evaluate_unlock(stats, "ciel")
        assert r["ready"] is False and r["unmet"], broken
    # approval is the ONE criterion ready never absorbs:
    r = tiers.evaluate_unlock(dict(good, user_approval=False), "ciel")
    assert r["unmet"] == ["user approval"]


def test_great_sage_has_no_unlock_and_unknown_tier_refused():
    assert tiers.evaluate_unlock({}, "great_sage")["ready"] is False
    assert "unknown tier" in tiers.evaluate_unlock({}, "GOD")["unmet"][0]
