# infra → integrator: protocol-loopback-bind
Status: OPEN

## What

Sync the shared contract with the Wave-2 network-security fix (session brief
task 2: "the Brain should bind 127.0.0.1 wherever the networking mode allows").
Code already changed on the infra side (`brain/run.py` default `127.0.0.1`
both modes, relay audited — see `scripts/NETWORK-SECURITY.md`).

1. **`docs/PROTOCOL.md` §1 Bind row** — currently says NAT mode binds
   `0.0.0.0:8765`. Proposed:

   > | Bind | `127.0.0.1:8765` in BOTH networking modes (loopback contract).
   > In NAT mode Windows clients reach the Brain through the supervisor's
   > user-space relay (Windows `127.0.0.1` → VM NAT address → Brain
   > loopback) or, once the optional narrow Hyper-V rule
   > (`scripts/win/allow-brain-localhost.ps1`) is applied, through native
   > WSL localhost forwarding. `RAPHAEL_BIND` is the explicit escape hatch
   > (`0.0.0.0` only when the relay is disabled AND native forwarding is
   > verified). In mirrored mode loopback is shared natively. |

2. **PROTOCOL §"WSL IP churn" fallback** — the "retry against the live WSL
   IP" fallback no longer applies once the Brain is loopback-only (direct
   `win→<vm-ip>:8765` must NOT work anymore — that path is the vulnerability
   being closed). Proposed: replace it with "Windows clients always use
   `127.0.0.1:<port>` via the supervisor relay (or native forwarding after
   the narrow rule); a direct VM-IP connection is expected to fail by design."

3. **`config.yaml → server.host: 0.0.0.0`** — key is currently read by no
   code (verified by grep), but the comment "WSL NAT localhostForwarding
   requires it" is now wrong. Proposed: `host: 127.0.0.1` + comment pointing
   at `scripts/NETWORK-SECURITY.md`.

## Why

Wave-2 network-security task (session brief #2). Leaving PROTOCOL at
`0.0.0.0` would make future lanes implement the insecure bind, and the
stale fallback text would send them back to the VM-IP hole.

## Impact

Contract-only (PROTOCOL + config.yaml comment are integrator-owned — I did
not touch them). Runtime behavior change is already in my own files and is
covered by `supervisor/tests/` (30 green) + the documented live e2e path
(process mode already ran `--host 127.0.0.1` in the Wave-2 integration
smoke). Risk: a consumer outside the relay chain dialing the VM IP — none
found by grep (only supervisor's `_wsl_ip`, which feeds the relay helper).
