"""Core Guard verify + last-known-good / rollback helpers (design 01 §1.1, §2.6-2.7).

Safety properties baked in:
- hash verification is DELEGATED to qa-security's `tests/core_guard.py`
  (single source of truth; `--update` needs an integrator-approved request);
  if the tool or its manifest is missing, verification FAILS (fail-closed);
- `rollback_command` / `retag_command` only GENERATE command strings for the
  journal and for infra's out-of-band rollback — this module never executes a
  `git reset`/`revert` against the real repo (tests use throwaway tmp repos).

Owned by evolution-persona (OWNERSHIP.md); read-only over Core Guard files.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_TOOL = "tests/core_guard.py"
LKG_TAG = "last-known-good"


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=raphael-evolution", "-c",
         "user.email=raphael@localhost", *args],
        cwd=str(repo), capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def verify_core_guard(repo: Path = REPO_ROOT,
                      python: str = sys.executable) -> Tuple[bool, str]:
    """Run qa-security's manifest tool in `repo`. (False, reason) on ANY
    problem — drift, missing tool, missing manifest: the controller refuses
    to run (design 01 §6 rule 10 'fail closed')."""
    repo = Path(repo)
    tool = repo / GUARD_TOOL
    manifest = repo / "tests" / "core_guard_manifest.json"
    if not tool.is_file() or not manifest.is_file():
        return False, f"core guard tool/manifest missing under {repo}"
    try:
        out = subprocess.run([python, str(tool)], cwd=str(repo),
                             capture_output=True, text=True, timeout=60)
    except Exception as exc:  # noqa: BLE001 — any failure = refuse
        return False, f"core guard verification could not run: {exc}"
    msg = (out.stdout + out.stderr).strip()
    return out.returncode == 0, msg or f"exit {out.returncode}"


def tag_last_known_good(repo: Path, commit: str,
                        journal_id: str = "") -> str:
    """Point the `last-known-good` tag at `commit` (moves with -f) AFTER a
    promote passes its gates (design 01 §2.6). Returns the tag's new target."""
    _git(Path(repo), "tag", "-f", "-a", LKG_TAG, str(commit), "-m",
         f"last-known-good {journal_id}".strip())
    return last_known_good(repo)


def last_known_good(repo: Path) -> Optional[str]:
    """Current LKG target commit, or None when the tag was never created."""
    try:
        return _git(Path(repo), "rev-list", "-n", "1", LKG_TAG) or None
    except RuntimeError:
        return None


def rollback_command(commit: str) -> str:
    """Command string recorded in the journal for a promoted change."""
    return f"git revert --no-edit {commit}"


def retag_command(commit: str) -> str:
    """Probation-failure command: re-point LKG at the previous good commit
    (infra executes this out-of-band — it must work with the Brain down)."""
    return f"git tag -f -a {LKG_TAG} {commit} -m probation rollback"
