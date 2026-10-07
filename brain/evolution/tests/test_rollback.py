"""Core Guard verify + LKG/rollback helper tests (design 01 §1.1, §2.6-2.7).

Git operations are exercised only against throwaway tmp repos — the real repo
is touched READ-ONLY (verify_core_guard runs qa-security's tool, no writes).
"""
import subprocess

import pytest

from brain.evolution import rollback as R


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(repo), check=True, capture_output=True, text=True)


@pytest.fixture
def tmp_repo(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "f.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "first")
    return tmp_path


def test_verify_core_guard_on_real_repo():
    """Real check against the real tree (read-only) — qa-security's tool."""
    ok, msg = R.verify_core_guard()
    assert ok, msg
    assert "byte-stable" in msg or "OK" in msg


def test_verify_fails_closed_when_tool_missing(tmp_path):
    ok, msg = R.verify_core_guard(tmp_path)
    assert not ok
    assert "missing" in msg


def test_lkg_tag_created_and_moved(tmp_repo):
    assert R.last_known_good(tmp_repo) is None          # no tag yet
    first = R._git(tmp_repo, "rev-parse", "HEAD")
    assert R.tag_last_known_good(tmp_repo, first, "evo_1") == first

    (tmp_repo / "f.txt").write_text("two\n", encoding="utf-8")
    _git(tmp_repo, "commit", "-q", "-am", "second")
    second = R._git(tmp_repo, "rev-parse", "HEAD")
    assert R.tag_last_known_good(tmp_repo, second, "evo_2") == second
    assert R.last_known_good(tmp_repo) == second        # moved forward


def test_command_strings_are_generated_never_executed(tmp_repo):
    head = R._git(tmp_repo, "rev-parse", "HEAD")
    assert R.rollback_command(head) == f"git revert --no-edit {head}"
    assert R.retag_command(head) == f"git tag -f -a last-known-good {head} -m probation rollback"
    # generating a command must not move the tag
    assert R.last_known_good(tmp_repo) is None


def test_revert_command_actually_applies_in_tmp_repo(tmp_repo):
    """The recorded rollback command must be a REAL working command (tmp repo)."""
    first = R._git(tmp_repo, "rev-parse", "HEAD")
    (tmp_repo / "f.txt").write_text("changed\n", encoding="utf-8")
    _git(tmp_repo, "commit", "-q", "-am", "change")
    _git(tmp_repo, "revert", "--no-edit", R._git(tmp_repo, "rev-parse", "HEAD"))
    assert (tmp_repo / "f.txt").read_text(encoding="utf-8") == "one\n"
    assert R.last_known_good(tmp_repo) is None
    assert first
