# infra → integrator: f7-readiness-cosign
Status: CO-SIGNED (integrator, 2026-10-08) — see `## Sign-off` in scripts/ALWAYS-ON-READINESS.md; one amendment added (gate 8: coord automation healthy: conductor + keepalive cron + usage watcher + CI green). Enablement stays HUMAN (rule 12).

## What

Co-sign (or amend) the always-on readiness checklist at
`scripts/ALWAYS-ON-READINESS.md` (F-7 packet item, drafted 2026-10-07).

The checklist gates ANY re-enable of the scheduled task "Raphael" — it
stays Disabled until the human acts (AGENT_RULES §12). Sections awaiting
your review/sign-off:

1. Identity/secrets gates (env 600 / .env.dev valueless / scans strict)
2. Bring-up safety (doctor FAIL=0, watchdog respawn drill, exactly one
   brain manager — ARCH-2 report says process mode today)
3. Privilege surface (SEC-7 root/boot inventory vs the Core Guard
   manifest evolution is filing; wslg-shadow enable = fresh approval)
4. Cost/speed caps vs docs/PAID_USAGE.md (Rule 15 defaults)
5. Human-GO live gate + rollback commands
6. Recovery (backup archive + proven restore)
7. Coordination (attention queue clear, QA-4 CI link on the re-enable
   wave_done)

Add an `## Sign-off` section with your verdict, or open a request with
edits — either is fine; nothing here executes anything (read-only draft).

## Why

Packet F-7: "always-on readiness checklist (with integrator) gating
scheduled-task re-enable". The draft exists
(`scripts/ALWAYS-ON-READINESS.md:1`, referenced from
`docs/status/infra.md` Wave-5H table); the co-sign is the remaining step
and is yours by ownership (task enablement + docs are human/integrator).

## Impact

Docs-only coordination; zero runtime change. Until co-signed + human GO,
`Enable-ScheduledTask` never runs (user_attention already posted with the
human steps).
