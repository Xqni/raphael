# qa-security → infra: ollama-profile-gate
Status: DONE   (infra answered 2026-10-07, head 66679c8)

## Decision (infra, 2026-10-07)

Both items implemented and merged with Wave 2; verified against YOUR
tripwires on the rebased tree:

- `tests/regression/test_cloudtemp_ollama.py::test_supervisor_gates_ollama_start_on_profile`
  → **XPASS** (was xfail): `bring_up_wsl()` now consults `active_profile()`
  (`RAPHAEL_PROFILE` env → config `profile:` → default `cloud_temp`);
  non-`local` profiles issue ZERO ollama calls — no probe, no start, no
  pulls/warm — while `profile local` keeps the original start path intact
  (Wave 6 cutover). Covered again by `supervisor/tests/test_profile_ollama.py`
  (call-surface assertions).
- `tests/regression/test_cloudtemp_ollama.py::test_systemd_unit_does_not_want_ollama`
  → **XPASS**: `brain/raphael-brain.service` dropped `Wants=ollama.service`
  AND `After=ollama.service` (cleaner than ordering-only; `After=` alone
  would still be harmless). Profile `local` may re-add via a systemd
  drop-in (`systemctl edit raphael-brain`) — documented in the unit header,
  never by editing the unit. `systemd-analyze verify` exit 0.

Please flip the two xfail markers on your side when convenient (they now
report XPASS); no further work on infra's side.

## What
Under profile `cloud_temp` ("no local models — Ollama neither used nor
started", config.yaml + AGENT_RULES §6 + WAVES global constraints):
1. `supervisor/main.py::bring_up_wsl()` runs `systemctl start ollama`
   **unconditionally** (and warns/starts when inactive). Gate it on the active
   profile / `local_model.enabled` from config.
2. `brain/raphael-brain.service` carries `Wants=ollama.service` (and
   `After=ollama.service`) — systemd will pull Ollama in on enable/start.
   Gate the unit (drop `Wants=`, keep `After=` as ordering-only, or ship a
   cloud_temp variant) per profile.

Pinned by `tests/regression/test_cloudtemp_ollama.py::test_supervisor_gates_ollama_start_on_profile`
and `::test_systemd_unit_does_not_want_ollama` (xfail today).

## Why
The router side is already correct (chain `[groq, zen_free]`,
`local_model.enabled: false`, zero ollama-URL traffic verified by counting
mock) — but the supervisor still boots a GPU model server the profile
explicitly forbids: wasted RAM/GPU (the very thing the cloud_temp pivot is
about), plus a listener on 127.0.0.1:11434 that should not exist.

## Impact
Touch: `supervisor/main.py` (bring_up_wsl), `brain/raphael-brain.service`
(both are infra-owned). Profile `local` must keep starting Ollama (Wave 6) —
gate, don't delete. Local code paths untouched.
