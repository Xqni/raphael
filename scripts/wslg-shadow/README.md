# scripts/wslg-shadow/ — WSLg weston shadow-kill wrapper (SEC-2 hardened)

Keeps the Weston `enable_window_shadow_remoting` kill-switch wrapper
installed across `wsl --shutdown` (the WSLg system-distro overlay resets).

## SECURITY (SEC-2, confirmed live 2026-10-07)

The pre-hardening chain was a local **privilege escalation**: the root boot
unit executed `/home/dami/scripts/raphael-wslg-shadow.sh` (user-writable),
which had root run `/mnt/wslg/raphael-shadow-fix/install.sh` (user-writable
shared mount) inside the system distro, which then copied a user-writable
`weston-wrapper` over `/usr/bin/weston`.

Current chain — every hop root-owned or SHA-256-pinned:

| step | who trusts what | anchor |
|---|---|---|
| 1 | unit (`/etc/systemd/system/…`, root) verifies `@BOOT_SHA@` of the payload before exec | root-owned unit |
| 2 | `wslg-boot.sh` (`/usr/local/lib/raphael/`, root:root) runs `sha256sum -c SHA256SUMS` over `wslg-install.sh` + `weston-wrapper` | root-owned pins |
| 3 | payloads reach the system distro via a **tar pipe (stdin)** — root there never reads `/mnt/wslg` as code — re-verifies the pins, then `wslg-install.sh` verifies the wrapper pin **again** before any `/usr/bin/weston` mutation | pinned bytes |

## Human steps (agents never run these — AGENT_RULES §12)

```bash
# preview (no sudo):
scripts/wslg-shadow/install-rooted.sh --dry-run
# install / refresh (idempotent), then run once to verify:
sudo scripts/wslg-shadow/install-rooted.sh --now
# check:
systemctl status raphael-wslg-shadow
sha256sum -c /usr/local/lib/raphael/SHA256SUMS
# after installing, drop the OLD user-writable payload:
rm -f ~/scripts/raphael-wslg-shadow.sh
# ROLLBACK:
sudo scripts/wslg-shadow/uninstall-rooted.sh --dry-run
sudo scripts/wslg-shadow/uninstall-rooted.sh
```

## ARCH-1 (native Windows orb) — removal plan

If the orb moves to a Windows-native renderer, the Weston/WLSG wrapper
becomes unnecessary: `sudo scripts/wslg-shadow/uninstall-rooted.sh`, then
restore stock weston if inside a cycle (see the `--help` text), and delete
this directory. No Node installs without explicit user approval.

## Files

- `raphael-wslg-shadow.service` — unit TEMPLATE (`@BOOT_SHA@`/`@LIB@`
  substituted by the installer)
- `boot-hook.sh` — source of the root-owned boot payload (`wslg-boot.sh`)
- `install.sh` — system-distro installer (pin-verified wrapper, backup-first)
- `weston-wrapper` — the env-only compositor wrapper itself
- `install-rooted.sh` / `uninstall-rooted.sh` — idempotent install/rollback
