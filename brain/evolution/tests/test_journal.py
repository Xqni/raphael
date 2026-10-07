"""Journal tests (design 01 §4): schema validation, roundtrip, index, summary."""
import pytest

from brain.evolution import journal as J


def _entry(**over):
    base = dict(finding="skills dedup threshold tuned", zone="mutable",
                paths=["skills/cooking/SKILL.md"], reason="Jaccard gate too loose",
                tests="pytest brain/evolution/tests -q -> 12 passed",
                decision="promoted", mode="auto_safe", diff_commit="abc1234")
    base.update(over)
    return J.make_entry(**base)


def test_promoted_entry_gets_rollback_command():
    e = _entry()
    assert e["decision"] == "promoted"
    assert e["rollback"] == "git revert --no-edit abc1234"
    assert e["id"].startswith("evo_") and e["ts"] > 0


def test_non_tree_changes_need_no_rollback():
    e = _entry(decision="proposal", diff_commit=None, rollback=None)
    assert e["rollback"] is None


@pytest.mark.parametrize("bad", ["merged", "PROMOTED", ""])
def test_bad_decision_rejected(bad):
    with pytest.raises(ValueError):
        _entry(decision=bad)


def test_bad_mode_rejected():
    with pytest.raises(ValueError):
        _entry(mode="always")


def test_write_and_roundtrip(tmp_path):
    e = _entry()
    path = J.write_entry(tmp_path, e)
    assert path.exists() and path.name.endswith(".md")
    loaded = J.load_entry(path)
    assert loaded["decision"] == "promoted"
    assert loaded["paths"] == ["skills/cooking/SKILL.md"]
    assert loaded["rollback"] == e["rollback"]
    body = path.read_text(encoding="utf-8")
    assert "## Reason" in body and "## Tests (real output only)" in body
    assert "git revert --no-edit abc1234" in body


def test_index_accumulates_unique_lines(tmp_path):
    J.write_entry(tmp_path, _entry())
    J.write_entry(tmp_path, _entry(finding="second change"))
    J.write_entry(tmp_path, _entry())          # duplicate write -> same line once
    index = (tmp_path / "INDEX.md").read_text(encoding="utf-8")
    lines = [l for l in index.splitlines() if l.startswith("- ")]
    assert len(lines) == 2, lines


def test_iter_entries_skips_index(tmp_path):
    J.write_entry(tmp_path, _entry())
    J.write_entry(tmp_path, _entry(decision="rolled_back",
                                   finding="probation failure"))
    entries = J.iter_entries(tmp_path)
    assert len(entries) == 2
    assert {e["decision"] for e in entries} == {"promoted", "rolled_back"}


def test_weekly_summary_counts_and_pending(tmp_path):
    assert J.weekly_summary(tmp_path) == "No evolution changes in the last week."
    J.write_entry(tmp_path, _entry())
    J.write_entry(tmp_path, _entry(decision="proposal", finding="core patch"))
    J.write_entry(tmp_path, _entry(decision="rejected", finding="too risky"))
    s = J.weekly_summary(tmp_path)
    assert "3 journal entries" in s
    assert "1 proposal awaits your approval" in s
    assert "promoted" in s and "rejected" in s


def test_weekly_summary_stale_entries_excluded(tmp_path):
    import time
    old = int((time.time() - 30 * 86400) * 1000)
    J.write_entry(tmp_path, _entry(ts=old, finding="ancient change"))
    assert J.weekly_summary(tmp_path, days=7) == "No evolution changes in the last week."
