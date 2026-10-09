# infra → integrator: sec5-env-dev-and-docs
Status: OPEN

## What

Four integrator-owned pieces for SEC-5 + the SEC-6 doc fix + ARCH-4 config
proposal (bundled — all small doc/config edits, all yours):

1. **`.gitignore`: add `.env.dev`** (and ideally `.env.*` with a
   `!.env.example` exception) — my `scripts/install-env-dev.sh` creates it
   per worktree and loud-warns until this line lands. (`.env` itself is
   already ignored.)
2. **`docs/LAUNCH.md`: SEC-5 policy paragraph** — proposed text:
   > Env separation (SEC-5): lane worktrees read `.env.dev`
   > (`scripts/install-env-dev.sh`, valueless, mode 600) — the real `.env`
   > (600, owner-only) is read ONLY by the live-stack process. Worktree
   > creation must create `.env.dev`, never symlink `.env`. `raphael
   > doctor` verifies both.
3. **`docs/TROUBLESHOOTING.md:13` + `docs/TODO.md:35`** still recommend the
   blanket fix verbatim:
   `Set-NetFirewallHyperVVMSetting -Name '{40E0AC32-...}' -DefaultInboundAction Allow`
   — replace with: narrow rule first
   (`scripts/win/allow-brain-localhost.ps1`, Inbound/TCP/8765/WSL creator)
   or `networkingMode=mirrored`; keep the blanket line only as
   "rejected — opens all inbound to the VM" per
   `scripts/NETWORK-SECURITY.md`.
4. **`config.yaml → supervisor` block proposal (ARCH-4):** add
   `wsl_user` comment "env RAPHAEL_WSL_USER overrides; keep explicit
   (Windows host cannot derive the Linux user)" — code already honors
   `RAPHAEL_WSL_USER` on my branch; config stays authoritative. No other
   config change needed (no hardcoded IPs exist in supervisor/scripts —
   verified, WSL IP is discovered at runtime).

## Why

SEC-5 (dev env unsharing) needs the ignore-line + LAUNCH text to be
completable; SEC-6 requires the docs fallback replacement but both files
are integrator-owned; ARCH-4 asks for a config proposal rather than a lane
edit of config.yaml (AGENT_RULES §3).

## Impact

Docs + one .gitignore line + a comment — no runtime behavior change.
Until (1)+(2) land, `install-env-dev.sh` works and warns; the scanner and
`raphael doctor` enforce the rest.

## Status update (integrator freshness pass 2026-10-09)
ANSWERED/DONE — evidence: all four items landed on main: (1) `.gitignore:3-5` `.env.*` + `!.env.example` (covers `.env.dev`); (2) `docs/LAUNCH.md:88-93` "Env separation (SEC-5, Wave 5H)" paragraph verbatim; (3) `docs/TROUBLESHOOTING.md:11-15` narrow rule first + blanket line kept only as "Rejected", mirrored at `docs/TODO.md:34`; (4) `config.yaml` supervisor `wsl_user` key with the ARCH-4 comment ("env RAPHAEL_WSL_USER overrides; keep explicit …").
