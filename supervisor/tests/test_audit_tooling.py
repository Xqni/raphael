"""Wave-5H audit tooling tests: SEC-1 scanner, SEC-5 env-dev, ARCH-7
backup/restore. Synthetic — temp dirs only, value-blind assertions."""
import importlib.util
import os
import subprocess
import sys
import tarfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = _ROOT / "scripts"


def _load_scanner():
    spec = importlib.util.spec_from_file_location(
        "scan_personal_under_test", SCRIPTS / "scan_personal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# SEC-1 — personal-data scanner (value-blind)
# --------------------------------------------------------------------------
def test_scanner_detects_and_allowlists(tmp_path, monkeypatch):
    mod = _load_scanner()
    real = tmp_path / "real.txt"
    real.write_text("host: jxesu box at /home/dami\n", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    found = mod.scan_file("real.txt")
    ids = {rid for rid, _ in found}
    assert "user-windows" in ids and "path-home" in ids
    # allowlisted paths report nothing even when loaded with patterns
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "scan_personal.py").write_text("jxesu /home/dami")
    assert mod.scan_file("scripts/scan_personal.py") == []


def test_scanner_full_scan_is_value_blind_and_advisory():
    r = subprocess.run(
        ["python3", str(SCRIPTS / "scan_personal.py")],
        capture_output=True, text=True, cwd=_ROOT)
    assert r.returncode == 0, r.stdout + r.stderr      # advisory default
    out = r.stdout
    # findings reference file:line + rule ids ONLY — never matched text
    assert "jxesu" not in out, "scanner leaked the Windows username"
    assert "rule=" in out and "finding(s)" in out


def test_scanner_empty_staged_is_clean():
    r = subprocess.run(
        ["python3", str(SCRIPTS / "scan_personal.py"), "--staged"],
        capture_output=True, text=True, cwd=_ROOT)
    assert r.returncode == 0                           # advisory, never blocks


def test_gitleaks_ledger_allowlisted_but_real_leak_still_fails(tmp_path,
                                                               monkeypatch):
    """qa request scan-personal-baseline-allowlist: the EXACT ledger path is
    suppressed, while an identical real leak ANYWHERE else still fails —
    and the allowlist carries no tests/** wildcard."""
    mod = _load_scanner()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    (tmp_path / "tests" / "security").mkdir(parents=True)
    (tmp_path / "tests" / "security" / "gitleaks-baseline.json").write_text(
        '{"findings": [{"match": "jxesu", "file": "/home/dami/x"}]}',
        encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "leak.md").write_text("host: jxesu at /home/dami\n",
                                               encoding="utf-8")
    # LEDGER: suppressed (allowlisted)
    assert mod.scan_file("tests/security/gitleaks-baseline.json") == []
    # REAL leak OUTSIDE the ledger: still detected
    hits = mod.scan_file("docs/leak.md")
    assert hits, "a real leak outside the ledger must still fail"
    ids = {rid for rid, _ in hits}
    assert "user-windows" in ids and "path-home" in ids
    # exact-path policy: the ONLY ^tests/ entry is the exact ledger path —
    # no wildcard over tests/**
    assert r"^tests/security/gitleaks-baseline\.json$" in mod.ALLOWLIST.pattern
    assert mod.ALLOWLIST.pattern.count("^tests/") == 1
    assert "tests/.*" not in mod.ALLOWLIST.pattern
    assert "tests/**" not in mod.ALLOWLIST.pattern


def test_summary_reports_allowlist_skips(capsys):
    r = subprocess.run(
        ["python3", str(SCRIPTS / "scan_personal.py")],
        capture_output=True, text=True, cwd=_ROOT)
    out = r.stdout
    assert "allowlist-skipped" in out
    assert "non-ledger" in out
    assert "finding(s)" in out


def test_precommit_hook_installer_idempotent(tmp_path):
    # static: hook content is advisory (never blocks)
    src = (SCRIPTS / "install-git-hooks.sh").read_text()
    assert '|| true' in src and "exit 0" in src
    assert "REFUSING" in src                           # won't clobber others
    assert "--uninstall" in src


# --------------------------------------------------------------------------
# SEC-5 — .env.dev (valueless dev env)
# --------------------------------------------------------------------------
def test_env_dev_template_is_valueless_and_keyless():
    tpl = (SCRIPTS / "env.dev.template").read_text()
    active = "\n".join(line for line in tpl.splitlines()
                        if line.strip() and not line.strip().startswith("#"))
    # no ACTIVE lines at all => no values AND no GROQ/GITHUB/cloud keys
    # (comments may mention those names as prohibitions)
    assert active.strip() == "", active


def test_install_env_dev_idempotent_and_guards(tmp_path):
    r = subprocess.run(
        ["sh", str(SCRIPTS / "install-env-dev.sh"),
         "--target", str(tmp_path)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "mode 600" in out and "value-blind check PASS" in out
    env = tmp_path / ".env.dev"
    assert oct(env.stat().st_mode)[-3:] == "600"
    # second run: kept (not clobbered)
    env.write_text("# hand edit\n")
    r2 = subprocess.run(
        ["sh", str(SCRIPTS / "install-env-dev.sh"),
         "--target", str(tmp_path)],
        capture_output=True, text=True)
    assert "hand-edited" in r2.stdout
    assert env.read_text() == "# hand edit\n"
    # --force resets a hand-edited file back to the valueless template
    bad = tmp_path / ".env.dev"
    bad.write_text("GROQ_API_KEY=sk-realvalue\n")
    r3 = subprocess.run(
        ["sh", str(SCRIPTS / "install-env-dev.sh"),
         "--target", str(tmp_path), "--force"],
        capture_output=True, text=True)
    assert r3.returncode == 0       # --force rewrote from template (valueless)
    r4 = subprocess.run(
        ["sh", str(SCRIPTS / "install-env-dev.sh"),
         "--target", str(tmp_path)],
        capture_output=True, text=True)
    assert r4.returncode == 0 and "PASS" in r4.stdout


# --------------------------------------------------------------------------
# ARCH-7 — backup/restore round trip in temp dirs
# --------------------------------------------------------------------------
def test_backup_restore_roundtrip(tmp_path):
    home = tmp_path / "home"
    data = home / ".raphael"
    (data / "orb" / "Cache").mkdir(parents=True)
    (data / "token").write_text("faketoken-not-real")
    (data / "memory.db").write_bytes(b"sqlite-bytes")
    (data / "orb" / "Cache" / "junk.bin").write_bytes(b"x" * 4096)
    (data / "orb" / "keepme.txt").write_text("orb-state")
    dest = tmp_path / "backups"

    env = dict(os.environ)
    env["RAPHAEL_HOME"] = str(home)
    env["BACKUP_DIR"] = str(dest)
    r = subprocess.run(["sh", str(SCRIPTS / "backup-raphael.sh")],
                       capture_output=True, text=True, env=env, cwd=_ROOT)
    assert r.returncode == 0, r.stderr
    archives = list(dest.glob("raphael-*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0]) as tf:
        names = tf.getnames()
    assert ".raphael/token" in names
    assert ".raphael/memory.db" in names
    assert ".raphael/orb/keepme.txt" in names
    assert "config/config.yaml" in names
    assert not any("Cache" in n for n in names)        # caches excluded

    # restore into a FRESH root (test mode: config lands inside --root)
    home2 = tmp_path / "home2"
    # pre-existing data -> safety copy must appear
    (home2 / ".raphael").mkdir(parents=True)
    (home2 / ".raphael" / "old.txt").write_text("old")
    r2 = subprocess.run(
        ["sh", str(SCRIPTS / "restore-raphael.sh"),
         "--from", str(archives[0]), "--root", str(home2), "--yes"],
        capture_output=True, text=True, env=env, cwd=_ROOT)
    assert r2.returncode == 0, r2.stderr
    assert (home2 / ".raphael" / "token").read_text() == "faketoken-not-real"
    assert oct((home2 / ".raphael" / "token").stat().st_mode)[-3:] == "600"
    assert (home2 / "config.yaml").is_file()       # config/ prefix stripped
    assert list(home2.glob(".raphael.pre-restore.*")), "no safety copy"


def test_restore_requires_archive(tmp_path):
    r = subprocess.run(
        ["sh", str(SCRIPTS / "restore-raphael.sh"), "--root",
         str(tmp_path), "--yes"],
        capture_output=True, text=True)
    assert r.returncode == 2
    assert "--from" in (r.stdout + r.stderr)
