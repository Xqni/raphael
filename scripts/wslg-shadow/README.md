# scripts/wslg-shadow/ — WSLg weston shadow-kill wrapper (SEC-2 hardened)

Keeps the Weston `enable_window_shadow_remoting` kill-switch wrapper
installed across `wsl --shutdown` (the WSLg system-distro overlay resets).

## SECURITY (SEC-2, confirmed live 2026-10-07 — LIVE UNIT DISABLED BY HUMAN)

The pre-hardening chain was a local **privilege escalation**: the root boot
unit executed `/home/dami/scripts/raphael-wslg-shadow.sh` (user-writable),
which had root run `/mnt/wslg/raphael-shadow-fix/install.sh` (user-writable
shared mount) inside the system distro, which then copied a user-writable
`weston-wrapper` over `/usr/bin/weston`.

**Status:** the human ran `systemctl disable --now raphael-wslg-shadow`
(2026-10-07) — the live threat is NEUTRALIZED and the unit must stay
disabled; re-enabling requires a **fresh human approval** (coordinator
decision). Repo-side: **KEEP + HARDENED** (decision — ARCH-1 has not
landed yet, so the shadow-kill wrapper is still wanted; retirement trigger
at the bottom).

Current chain — every hop root-owned or SHA-256-pinned:

| step | who trusts what | anchor |
|---|---|---|
| 1 | unit (`/etc/systemd/system/…`, root) verifies `@BOOT_SHA@` of the payload before exec | root-owned unit |
| 2 | `wslg-boot.sh` (`/usr/local/lib/raphael/`, root:root) runs `sha256sum -c SHA256SUMS` over `wslg-install.sh` + `weston-wrapper` | root-owned pins |
| 3 | payloads reach the system distro via a **tar pipe (stdin)** — root there never reads `/mnt/wslg` as code — re-verifies the pins, then `wslg-install.sh` verifies the wrapper pin **again** before any `/usr/bin/weston` mutation | pinned bytes |

The installer additionally **FAILS LOUD** (refuses to install) if the
rendered unit would exec anything outside the root-owned
`/usr/local/lib/raphael` tree (no `/home`, no `/mnt`). Backup data
(`weston.bin.orig`) still lives on `/mnt/wslg` — data only, never
executed.

## Human steps (agents never run these — AGENT_RULES §12)

```bash
# preview (no sudo):
scripts/wslg-shadow/install-rooted.sh --dry-run
# install the hardened chain, LEAVING IT DISABLED (default policy):
sudo scripts/wslg-shadow/install-rooted.sh
# arm it — ONLY with a fresh human approval, then optionally run once:
sudo scripts/wslg-shadow/install-rooted.sh --enable
sudo scripts/wslg-shadow/install-rooted.sh --enable --now
# check:
systemctl status raphael-wslg-shadow
sha256sum -c /usr/local/lib/raphael/SHA256SUMS
# after installing, drop the OLD user-writable payload:
rm -f ~/scripts/raphael-wslg-shadow.sh
# ROLLBACK / full retire:
sudo scripts/wslg-shadow/uninstall-rooted.sh --dry-run
sudo scripts/wslg-shadow/uninstall-rooted.sh
```

## ARCH-1 (native Windows orb) — retirement decision & plan

Decision 2026-10-07: **keep + harden now, retire when ARCH-1 lands.**
When the orb moves to a Windows-native renderer, the Weston/WSLg wrapper
becomes unnecessary: `sudo scripts/wslg-shadow/uninstall-rooted.sh`
(unit + root payload removed, idempotent), restore stock weston if inside
a cycle (see the `--help` text), delete this directory, and drop the
supervisor-side wrapper doc reference. No Node installs without explicit
user approval.

## Files

- `raphael-wslg-shadow.service` — unit TEMPLATE (`@BOOT_SHA@`/`@LIB@`
  substituted by the installer)
- `boot-hook.sh` — source of the root-owned boot payload (`wslg-boot.sh`)
- `install.sh` — system-distro installer (pin-verified wrapper, backup-first)
- `weston-wrapper` — the env-only compositor wrapper itself
- `install-rooted.sh` / `uninstall-rooted.sh` — idempotent install/rollback
