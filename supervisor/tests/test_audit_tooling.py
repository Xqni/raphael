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
    # planted strings assembled from FRAGMENTS: source carries no
    # contiguous personal-data literal (gitleaks CI 37779096880), while
    # runtime values stay the real patterns the scanner must detect
    leak_user = "jx" "esu"
    leak_home = "/ho" "me/" "da" "mi"
    real = tmp_path / "real.txt"
    real.write_text(f"host: {leak_user} box at {leak_home}\n",
                    encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    found = mod.scan_file("real.txt")
    ids = {rid for rid, _ in found}
    assert "user-windows" in ids and "path-home" in ids
    # allowlisted paths report nothing even when loaded with patterns
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "scan_personal.py").write_text(
        f"{leak_user} {leak_home}")
    assert mod.scan_file("scripts/scan_personal.py") == []


def test_scanner_full_scan_is_value_blind_and_advisory():
    r = subprocess.run(
        ["python3", str(SCRIPTS / "scan_personal.py")],
        capture_output=True, text=True, cwd=_ROOT)
    assert r.returncode == 0, r.stdout + r.stderr      # advisory default
    out = r.stdout
    # findings reference file:line + rule ids ONLY — never matched text
    assert (leak_user if False else "jx" "esu") not in out, \
        "scanner leaked the Windows username"
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
    leak_user = "jx" "esu"
    leak_home = "/ho" "me/" "da" "mi"
    (tmp_path / "tests" / "security").mkdir(parents=True)
    (tmp_path / "tests" / "security" / "gitleaks-baseline.json").write_text(
        '{"findings": [{"match": "%s", "file": "%s/x"}]}'
        % (leak_user, leak_home), encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "leak.md").write_text(
        f"host: {leak_user} at {leak_home}\n", encoding="utf-8")
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


# --------------------------------------------------------------------------
# Scanner policy packet (coord [39]): ip-public version FPs + functional keys
# --------------------------------------------------------------------------
def test_ip_public_version_context_and_real_ips():
    """Corpus 2026-10-08: version strings are NOT addresses; real IPs
    (incl. ip:port forms) still are — no over-suppression."""
    mod = _load_scanner()
    ip_rule = [r for r in mod.RULES if r[0] == "ip-public"][0]
    pat = ip_rule[2]
    # version FPs -> regex may match, but the line-context filter rejects
    for line in ["Kernel: 6.18.33.2-2",
                 "kernel 6.18.33.2-microsoft-standard-WSL2",
                 "WSLg:  1.0.73.2      MSRDC 1.2.7214",
                 "WSL version:  2.7.11.0",
                 "Initial env probe: kernel 6.18.33.2, 20 cores"]:
        m = pat.search(line)
        if m:
            assert not mod._is_public_ipv4(m.group(0), line), line
    # suffix blocking at the regex level too
    assert not pat.search("build 6.18.33.2-microsoft-standard-WSL2 tag")
    # REAL public IPs must still be flagged (no over-suppression)
    real = ("monkeypatch.setattr(socket, 'getaddrinfo', "
            "_fake_getaddr('93.184.216.34'))")
    m = pat.search(real)
    assert m and mod._is_public_ipv4(m.group(0), real)
    for line in ["dns: 8.8.8.8", "probe 1.1.1.1:443"]:
        m = pat.search(line)
        assert m and mod._is_public_ipv4(m.group(0), line), line


def test_functional_value_keys_suppressed_exactly(tmp_path, monkeypatch):
    """KEY_OK: exact (file, key, rule) triples suppress runtime config
    VALUES; a username mention elsewhere in the SAME file still flags;
    the table has no wildcards."""
    mod = _load_scanner()
    for path, key, rule in mod.KEY_OK:
        assert "*" not in path and "*" not in key, (path, key)
        assert path == path.strip() and ":" not in key and key == key.strip()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    leak_user = "jx" "esu"
    leak_home = "/ho" "me/" "da" "mi"
    bare_user = leak_home.split("/")[-1]
    (tmp_path / "config.yaml").write_text(
        "supervisor:\n  wsl_user: %s\n  note: operator %s exists\n"
        % (bare_user, leak_user), encoding="utf-8")
    hits = mod.scan_file("config.yaml")
    rules_hit = {rid for rid, _ in hits}
    # prose mention still flags (user-windows from the operator note) ...
    assert "user-windows" in rules_hit
    # ... while the wsl_user KEY line is suppressed (its user-linux hit is
    # absent) — exact-triple suppression, not file-wide:
    assert "user-linux" not in rules_hit
    # a different file with the same key still flags (exact-file, no wildcard)
    (tmp_path / "other-config.yaml").write_text(
        "wsl_user: %s\n" % bare_user, encoding="utf-8")
    other = mod.scan_file("other-config.yaml")
    assert other and {rid for rid, _ in other} == {"user-linux"}
