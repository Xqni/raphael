"""AUD-26 regression tests: (1) path escapes are refused BEFORE any file
access, (2) `promoted` is truthful — promotion really merges (or fails closed
to proposal with the caller's dirty tree preserved)."""
import pytest

from brain.evolution import controller as C
from brain.evolution.controller import run_cycle, safe_rel
from brain.evolution.zones import Zone


# ---------------------------------------------------------------- path guard
@pytest.mark.parametrize("bad", [
    "/etc/passwd",
    "/tmp/absolute.yaml",
    "../escape.yaml",
    "a/../../escape.yaml",
    "~/.ssh/evil",
    "C:/windows/evil.yaml",
    "",
    "   ",
    ".",
    "./",
])
def test_safe_rel_rejects_escapes(bad, tmp_path):
    with pytest.raises(ValueError):
        safe_rel(tmp_path, bad)


def test_safe_rel_accepts_normal_repo_paths(tmp_path):
    assert safe_rel(tmp_path, "config.d/evolution-persona.yaml") == \
        "config.d/evolution-persona.yaml"
    assert safe_rel(tmp_path, "skills/a/SKILL.md") == "skills/a/SKILL.md"


def test_safe_rel_rejects_symlink_escape(tmp_path):
    base, outside = tmp_path / "repo", tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    (base / "link").symlink_to(outside)
    with pytest.raises(ValueError):
        safe_rel(base, "link/secret.yaml")
    assert not (outside / "secret.yaml").exists()


def test_refusal_happens_BEFORE_any_file_access(tmp_path, monkeypatch):
    """AUD-26: validation runs before the guard subprocess — prove the guard
    (first possible access) is never touched when a path is unsafe."""
    def _boom(*a, **k):
        raise AssertionError("core guard accessed before path validation")
    monkeypatch.setattr(C.R, "verify_core_guard", _boom)

    for bad in ("/etc/passwd", "../escape.yaml", "~/evil", "a/../b.yaml"):
        tr = run_cycle("auto_safe", {bad: "payload"}, ["none"],
                       repo=tmp_path, slug="escape")
        assert tr["status"] == "refused", tr
        assert "unsafe path" in tr["reason"]
        assert tr["steps"][0]["step"] == "path_guard"
        assert tr["steps"][0]["ok"] is False
    # nothing created anywhere
    assert list(tmp_path.iterdir()) == []


def test_worktree_write_is_revalidated(tmp_repo, monkeypatch):
    """Belt+braces: even if a path passed repo validation, the worktree write
    re-validates (symlink divergence between repo and fresh checkout)."""
    monkeypatch.setattr(
        C, "safe_rel",
        lambda base, rel: (_ for _ in ()).throw(ValueError("reval boom"))
        if "/evo-" in str(base) else rel)
    monkeypatch.setattr(C.R, "verify_core_guard",
                        lambda *a, **k: (True, "ok"))
    tr = run_cycle("propose", {"skills/a/SKILL.md": "x\n"}, ["none"],
                   repo=tmp_repo, slug="reval",
                   journal_dir=tmp_repo / "j", proposal_dir=tmp_repo / "p")
    assert tr["status"] == "refused"
    assert "unsafe path" in tr["reason"]
    assert any(s["step"] == "path_guard" and s.get("phase") == "worktree"
               and s["ok"] is False for s in tr["steps"])
    # the caller tree is untouched and the worktree was cleaned up
    assert not (tmp_repo / "skills").exists()


# ------------------------------------------------- truthful promotion (AUD-26)
def _stub(monkeypatch):
    monkeypatch.setattr(C.R, "verify_core_guard",
                        lambda *a, **k: (True, "Core Guard OK (stub)"))
    monkeypatch.setattr(C.S, "run_tests",
                        lambda *a, **k: {"ok": True, "rc": 0,
                                         "output": "160 passed", "derivation": {"ok": True}})
    monkeypatch.setattr(C.B, "capture",
                        lambda repo, res, transcripts=None: {
                            "commit": "0" * 40, "last_known_good": None,
                            "core_guard": {"ok": True, "msg": "ok"},
                            "shadow": {"ok": True, "rc": 0, "command": "",
                                       "output_tail": "160 passed"},
                            "transcripts": list(transcripts or [])})
    monkeypatch.setattr(C.B, "compare",
                        lambda cur, base: {"ok": True,
                                           "deltas": ["commit moved: a -> b"]})


def test_promoted_really_merges(tmp_repo, monkeypatch):
    _stub(monkeypatch)
    tr = run_cycle("auto_safe", {"skills/a/SKILL.md": "learned\n"},
                   ["t"], repo=tmp_repo, slug="promo",
                   journal_dir=tmp_repo / "j", proposal_dir=tmp_repo / "p")
    # truthful: status, journal decision AND the working tree all agree
    assert tr["status"] == "promoted" and tr["merged"] is True
    dec = [s for s in tr["steps"] if s["step"] == "decision"][0]
    assert dec["decision"] == "promoted" and dec["merged"] is True
    assert (tmp_repo / "skills" / "a" / "SKILL.md").read_text() == "learned\n"
    from brain.evolution import rollback as R
    assert R.last_known_good(tmp_repo) == tr["patch_commit"]   # LKG tagged
    assert not any(b.startswith("evo/") for b in
                   __import__("subprocess").run(
                       ["git", "branch"], cwd=tmp_repo, capture_output=True,
                       text=True).stdout.split())


def test_promotion_refused_on_dirty_tree_fails_closed(tmp_repo, monkeypatch):
    """A dirty file the merge would overwrite => git refuses => we fail CLOSED
    to proposal, keep the label truthful, and the dirty file is untouched."""
    _stub(monkeypatch)
    mine = tmp_repo / "skills"
    mine.mkdir()
    (mine / "a").mkdir()
    (mine / "a" / "SKILL.md").write_text("mine, uncommitted\n", encoding="utf-8")

    head_before = __import__("subprocess").run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_repo, capture_output=True,
        text=True).stdout.strip()

    tr = run_cycle("auto_safe", {"skills/a/SKILL.md": "patched\n"},
                   ["t"], repo=tmp_repo, slug="dirty",
                   journal_dir=tmp_repo / "j", proposal_dir=tmp_repo / "p")
    assert tr["status"] == "proposal_written"
    assert tr["merged"] is False
    dec = [s for s in tr["steps"] if s["step"] == "decision"][0]
    assert dec["decision"] == "proposal"
    assert "fail closed to proposal" in dec["reason"]
    # caller's dirty worktree preserved byte-for-byte
    assert (mine / "a" / "SKILL.md").read_text() == "mine, uncommitted\n"
    # HEAD unchanged (nothing merged)
    head_after = __import__("subprocess").run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_repo, capture_output=True,
        text=True).stdout.strip()
    assert head_after == head_before
    # proposal file exists and is the only artifact
    assert (tmp_repo / "p").is_dir()


def test_propose_mode_never_merges(tmp_repo, monkeypatch):
    _stub(monkeypatch)
    tr = run_cycle("propose", {"skills/a/SKILL.md": "x\n"}, ["t"],
                   repo=tmp_repo, slug="propose-only",
                   journal_dir=tmp_repo / "j", proposal_dir=tmp_repo / "p")
    assert tr["status"] == "proposal_written" and tr["merged"] is False
    assert not (tmp_repo / "skills").exists()   # nothing applied to caller tree


def test_refused_mode_gate_never_reaches_merge(tmp_repo, monkeypatch):
    _stub(monkeypatch)
    tr = run_cycle("off", {"skills/a/SKILL.md": "x\n"}, ["t"],
                   repo=tmp_repo, slug="off",
                   journal_dir=tmp_repo / "j", proposal_dir=tmp_repo / "p")
    assert tr["status"] == "skipped"
    assert not (tmp_repo / "skills").exists()


def test_classify_zone_used_by_gate():
    """The promotion gate needs MUTABLE — Core Guard targets never promote."""
    assert C.decide("auto_safe", Zone.CORE) == "proposal"
    assert C.decide("auto_safe", Zone.MUTABLE) == "promote"
