"""Shared fixtures for brain/evolution tests (RAM rule 14: tiny, self-contained,
git-only — no servers, no network)."""
import subprocess

import pytest


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(repo), check=True, capture_output=True, text=True)


@pytest.fixture
def tmp_repo(tmp_path):
    """Throwaway git repo with one committed file — never the real repo."""
    _git(tmp_path, "init", "-q")
    (tmp_path / "f.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "first")
    return tmp_path
