# Integrator → Core Guard: Wave 5U pinned-file approvals (standing, per-task)

Date: 2026-10-10. Owner-authorized sprint (docs/USEFUL-NOW-PLAN.md charter; pre-approvals
in AGENT_RULES rule 16).

Approvals granted IN ADVANCE for Wave 5U work on Core-Guard-pinned files, each still
requiring a CLEAN-tree `python3 tests/core_guard.py --update --approval docs/requests/integrator-core-guard-5u-sprint.md` at the moment of the change:

1. `brain/confirm.py` — P0.1/P0.2 confirm-policy wiring (brain-core; requested by their
   own lane request first, this grant covers the guard mechanics only).
2. `supervisor/**` — P0.5 relay-helper watchdog + health probe (infra).
3. `docs/OWNERSHIP.md` — further Wave-5U path grants (worldstate/agents/web-chat landed
   2026-10-10 under the charter).
4. `.github/workflows/ci.yml` — qa moving `scan_personal --strict` into CI (their task §5.5.6).
5. `body/win/act_powershell.py` — only if pc-control's browser work touches it (expected: NO).

Never approved: weakening any gate, removing a scanner, or editing a lane's tests to
make them pass. Re-pin from a clean tree; the manifest is the contract.
