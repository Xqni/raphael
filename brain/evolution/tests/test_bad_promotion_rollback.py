"""Forced bad promotion → rollback drill (Wave-5H audit task 3).

Scenario, entirely in a throwaway tmp repo (no live stack, no servers):
  1. baseline commit + `last-known-good` tag (the pre-promotion state);
  2. a BAD promotion lands (content regression on a mutable-zone file);
  3. its journal entry carries the rollback command (journal.make_entry auto-fill);
  4. probation starts after the approved unlock and fails FATAL (severity-1);
  5. rollback executes the JOURNAL'S recorded command + re-points LKG:
     the tree returns to the baseline content and LKG points at baseline;
  6. governance: the same bad promotion aimed at a Core Guard path would have
     been refused by the classifier (auto-promotable == False).

The supervisor's out-of-band hook itself does not exist yet (verified:
`grep -rn rollback supervisor/ --include='*.py'` = 0 matches) — the drill uses
the journal-recorded git command, which is the documented interim path
(design 01 §2.7; SEC-7 request adds supervisor/** to the hash manifest).
"""
import subprocess

from brain.evolution import journal as J
from brain.evolution import rollback as R
from brain.evolution import zones as Z


def _git(repo, *args, check=True):
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(repo), capture_output=True, text=True)
    if check and out.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {out.stderr}")
    return out.stdout.strip()


def test_forced_bad_promotion_triggers_rollback(tmp_repo):
    # 1. baseline + LKG
    (tmp_repo / "target.txt").write_text("good content\n", encoding="utf-8")
    _git(tmp_repo, "add", ".")
    _git(tmp_repo, "commit", "-q", "-m", "baseline")
    baseline = R._git(tmp_repo, "rev-parse", "HEAD")
    assert R.tag_last_known_good(tmp_repo, baseline, "evo_baseline") == baseline

    # 2. BAD promotion (mutable-zone regression)
    (tmp_repo / "target.txt").write_text("regressed content\n", encoding="utf-8")
    _git(tmp_repo, "commit", "-q", "-am", "bad promotion")
    bad_commit = R._git(tmp_repo, "rev-parse", "HEAD")
    assert (tmp_repo / "target.txt").read_text(encoding="utf-8") == "regressed content\n"

    # 3. journal entry records the rollback command automatically
    entry = J.make_entry(
        finding="bad auto-promotion", zone="mutable", paths=["target.txt"],
        reason="regression caught by probation", tests="shadow: FAILED (sim)",
        decision="promoted", mode="auto_safe", diff_commit=bad_commit)
    assert entry["rollback"] == f"git revert --no-edit {bad_commit}"

    # 4. probation fails fatally (severity-1 during the window)
    from brain.persona import probation as P
    st = P.start("great_sage", "raphael", {"jobs": 20, "hours": 24},
                 path=tmp_repo / "prob.json")
    P.record(st, ok=False, reason="severity-1 regression in promotion",
             fatal=True, path=tmp_repo / "prob.json")
    verdict = P.evaluate(st, path=tmp_repo / "prob.json")
    assert verdict["status"] == "failed"
    assert P.demotion_target(st["to_tier"]) == "great_sage"

    # 5a. execute the JOURNAL's recorded rollback command
    _git(tmp_repo, "revert", "--no-edit", bad_commit)
    assert (tmp_repo / "target.txt").read_text(encoding="utf-8") == "good content\n"

    # 5b. re-point LKG at the pre-promotion baseline (retag command semantics)
    _git(tmp_repo, "tag", "-f", "-a", R.LKG_TAG, baseline, "-m", "probation rollback")
    assert R.last_known_good(tmp_repo) == baseline
    # tree content matches baseline exactly
    diff = _git(tmp_repo, "diff", baseline, "HEAD", "--", "target.txt")
    assert diff == "", diff

    # journal the real outcome
    entry["decision"] = "rolled_back"
    entry["rollback"] = f"git revert --no-edit {bad_commit} (executed) + {R.retag_command(baseline)}"
    written = J.write_entry(tmp_repo / "journal", entry)
    reloaded = J.load_entry(written)
    assert reloaded["decision"] == "rolled_back"


def test_same_bad_promotion_on_core_guard_path_is_refused(tmp_repo):
    """Governance: a 'promotion' targeting the supervisor rollback path could
    never be auto-promoted — it classifies CORE (zones.py supervisor/**) and
    sha1 drift would also fail core-guard verify."""
    diff = "--- a/supervisor/main.py\n+++ b/supervisor/main.py\n+  rollback_enabled = False\n"
    assert not Z.is_auto_promotable(["supervisor/main.py"], diff)
    assert Z.zone("supervisor/main.py") is Z.Zone.CORE
    # content markers don't matter — the path alone is decisive (fail-closed)
    assert not Z.is_auto_promotable(["tools/conductor/conductor.py"], None)
    assert not Z.is_auto_promotable([".github/workflows/ci.yml"], None)
    # and the core-guard verifier refuses a drifted tree (real repo, read-only)
    ok, msg = R.verify_core_guard()
    assert ok, msg
