# qa-security → infra: ollama-profile-gate
Status: OPEN

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
