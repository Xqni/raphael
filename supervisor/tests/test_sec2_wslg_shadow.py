"""SEC-2 — WSLg-shadow privilege-escalation remediation checks.

All synthetic: static content assertions + unprivileged dry-runs + the
pin-refusal path of install.sh (exits BEFORE any /usr/bin mutation). No
sudo, no system distro, no weston touched."""
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
SHADOW = _ROOT / "scripts" / "wslg-shadow"


def test_unit_template_pins_payload_and_never_home_path():
    unit = (SHADOW / "raphael-wslg-shadow.service").read_text()
    assert "@BOOT_SHA@" in unit and "@LIB@" in unit      # rendered by installer
    assert "sha256sum -c" in unit                        # pin verified BEFORE exec
    assert "/home/dami" not in unit                      # the SEC-2 hole is gone
    assert "/home/" not in unit


def test_boot_hook_verifies_and_pipes_no_user_fs_code():
    boot = (SHADOW / "boot-hook.sh").read_text()
    # assertions run on CODE lines only (comments document the old chain)
    code = "\n".join(line for line in boot.splitlines()
                     if not line.lstrip().startswith("#"))
    # step 2: root-owned pins verified before anything else
    assert code.index("sha256sum -c SHA256SUMS") < code.index("tar -cf -")
    # step 3: payloads travel via stdin pipe (system distro re-verifies)
    assert 'tar -C "$D" -xf -' in code
    assert "sha256sum -c SHA256SUMS" in code.split("tar -C")[1]
    # the old hole: root executing shared-mount code, is GONE from code
    assert "$BACKUP/install.sh" not in code
    assert "sh /mnt" not in code
    # ARCH-4: every machine-specific path is overridable
    assert "RAPHAEL_WSLG_LIB" in code and "RAPHAEL_WSL" in code
    assert "RAPHAEL_WSLG_BACKUP" in code


def test_install_sh_requires_pin_and_refuses_mismatch(tmp_path):
    wrapper = tmp_path / "weston-wrapper"
    wrapper.write_text("#!/bin/sh\ntrue\n")
    backup = tmp_path / "backup"
    # no args -> usage, rc 2
    r = subprocess.run(["sh", str(SHADOW / "install.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "SEC-2" in (r.stdout + r.stderr)
    # wrong pin -> rc 3, refuses BEFORE touching /usr/bin/weston
    r = subprocess.run(
        ["sh", str(SHADOW / "install.sh"), str(backup), str(wrapper),
         "0" * 64],
        capture_output=True, text=True)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "MISMATCH" in (r.stdout + r.stderr)
    assert not backup.exists()           # no mutation happened at all


def test_install_rooted_dry_run_runs_unprivileged():
    r = subprocess.run(["sh", str(SHADOW / "install-rooted.sh"), "--dry-run"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "/usr/local/lib/raphael" in out          # root-owned target
    assert "SHA256SUMS" in out and "@BOOT_SHA@" in out
    assert "daemon-reload" in out
    # coordinator policy: DISABLED by default, enable needs approval
    assert "enable: NO" in out and "--enable" in out


def test_install_rooted_fails_loud_on_user_writable_exec():
    src = (SHADOW / "install-rooted.sh").read_text()
    # the fail-loud audits exist and check both forbidden classes
    assert "REFUSING to install" in src
    assert "user-writable content — REFUSING (SEC-2)" in src
    assert "/home/" in src and "/mnt/" in src        # the greps' patterns
    # default is disabled (policy: never re-enable without fresh approval)
    assert "systemctl disable raphael-wslg-shadow" in src


def test_uninstall_rooted_dry_run_rollback():
    r = subprocess.run(["sh", str(SHADOW / "uninstall-rooted.sh"),
                        "--dry-run"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "rm -rf /usr/local/lib/raphael" in out
    assert "raphael-wslg-shadow.service" in out
    assert "weston.bin.orig" in out                 # stock-weston restore doc


def test_readme_documents_chain_and_rollback():
    readme = (SHADOW / "README.md").read_text()
    assert "privilege escalation" in readme
    assert "install-rooted.sh" in readme and "uninstall-rooted.sh" in readme
    assert "ARCH-1" in readme                       # native-orb removal plan
