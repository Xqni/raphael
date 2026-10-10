# NETWORK-SECURITY.md — bind audit + localhost-only path (infra lane)

Last updated: 2026-10-06 (Wave 2 network-security task). Scope: where every
Raphael process binds, why, and how to get to end-to-end `127.0.0.1` without
ever loosening the firewall wholesale. Read together with `docs/PROTOCOL.md`
§1 and `docs/INTERFACES.md` §d.

## Principles

1. **The Brain never leaves loopback.** Default bind is `127.0.0.1` in BOTH
   WSL networking modes (`brain/run.py`); token auth on top (PROTOCOL §2).
   `RAPHAEL_BIND` is the explicit escape hatch (`0.0.0.0` only if you have
   deliberately disabled the relay *and* verified native forwarding).
2. **No wildcard binds anywhere in the relay chain.** The audit removed the
   helper's old `ip or "0.0.0.0"` fallback — one specific address or exit.
3. **No blanket firewall changes.** `-DefaultInboundAction Allow` (the
   usual fix) opens *all* inbound traffic to the WSL VM and is explicitly
   rejected. A narrow one-port rule is the only accepted firewall change —
   and it is optional, user-run, documented.
4. **Agents never run elevated commands** (AGENT_RULES §12). Every script
   below exists to be run by the user, by hand.

## Bind matrix (today, profile cloud_temp)

| Component | Bind address | Reachable from | Notes |
|---|---|---|---|
| Brain (`brain/run.py` / supervisor process mode `--host 127.0.0.1`) | `127.0.0.1` | WSL-local only | port = `RAPHAEL_INSTANCE`-derived (8765 main) |
| Supervisor Windows relay leg | `127.0.0.1` **only** (not configurable) | Windows-local only | `supervisor/main.py:_relay_listener` |
| WSL relay helper leg (`scripts/wsl-relay.py`) | **exactly one** address: the VM's NAT IP | Windows host only (NAT is not LAN-routable) | refuses to start rather than bind wildcard; not spawned at all in mirrored mode or when gated off |
| Fish TTS | `127.0.0.1:8777` (voice lane) | WSL-local only | never spawned by supervisor |
| Health probes / CLI / Body (Windows side) | dial `127.0.0.1:<port>` | — | via relay today, natively after the optional rule |

## Why the relay exists (verified 2026-10-05)

Windows' built-in WSL localhost forwarding is blocked by the Hyper-V
firewall on this machine:

- `win → 127.0.0.1:8765` — **refused**
- `win → <vm-ip>:8765` — connects

so Windows clients cannot reach a loopback-bound Brain natively. The
supervisor splices in user space (zero privileges):

```
Windows client  127.0.0.1:8765
   └─ supervisor relay leg  (binds 127.0.0.1 ONLY)
        └─ <vm NAT ip>:<helper>   scripts/wsl-relay.py (one specific address)
             └─ 127.0.0.1:8765  Brain (loopback — contract preserved)
```

Helper port derivation: main `8766` (historical), instances `port+1000`
(e.g. infra 8907 → helper 9907) so no helper can bind-clash with or
cross-route to another lane's brain.

**Why the helper leg cannot itself be `127.0.0.1`:** the Windows relay dials
it *over the vNIC* — packets from Windows arrive on the VM's eth0, never on
the guest loopback, and native Windows→WSL forwarding is precisely what is
firewalled here. The helper therefore binds the VM's NAT address (host-internal,
never LAN-routable) and **never** a wildcard. Everything Windows-side of it
is loopback-only.

## Getting to end-to-end 127.0.0.1 (pick one — both optional)

**Option A — mirrored networking (no script):** with
`networkingMode=mirrored` in `.wslconfig` (a *user* change — never touched
by agents, see AGENT_RULES §12), Windows and WSL share one loopback. The
supervisor auto-detects this (`wslinfo --networking-mode`) and skips the
relay + helper entirely. Note the WSL `.wslconfig` edit itself is the user's
call and requires `wsl --shutdown`.

**Option B — narrow firewall rule (recommended for NAT mode):**

```powershell
# as admin, user-run — never agent-run
scripts\win\allow-brain-localhost.ps1
```

creates ONE Hyper-V rule: `Inbound, TCP, LocalPort 8765, VMCreatorId = WSL`.
Then:

1. `config.yaml: paths.brain_relay: false` (helper gate
   `paths.brain_relay_helper: false` follows — nothing spawns it),
2. restart the supervisor,
3. verify: `curl.exe http://127.0.0.1:8765/health` → `200`/`401`, **not**
   refused (401 = reachable, token missing — still proof of forwarding),
4. rollback if refused: remove the rule
   (`Remove-NetFirewallHyperVRule -Name 'Raphael-Brain-8765'`) and set
   `paths.brain_relay: true` again.

WSL documents that localhostForwarding covers ports "bound to wildcard **or
localhost**" in the VM, which is why a loopback-bound Brain is reachable
once the firewall allows the forwarded connection. Step 3 is the empirical
check — if it fails on this machine, keep the relay (status quo, verified
working) and report it.

## Rejected options (recorded so they stay rejected)

| Option | Why rejected |
|---|---|
| `Set-NetFirewallHyperVVMSetting ... -DefaultInboundAction Allow` | blanket allow-all inbound to the WSL VM — explicitly forbidden by the task |
| Brain `0.0.0.0` in NAT mode | unnecessary once the relay chain exists; widens every LAN-facing interface |
| Helper leg `0.0.0.0` fallback (pre-audit code) | wildcard bind removed; no-NAT-address now exits 1 |
| `netsh interface portproxy` | host-global port forwarding (admin service, persists across reboots, wider blast radius) — not needed |

## Config switches (all in `config.yaml → paths`, lane-owned key space)

| key | default | meaning |
|---|---|---|
| `brain_relay` | `true` | Windows 127.0.0.1 splice on/off (off = native forwarding must be verified) |
| `brain_relay_helper` | `true` | spawn the WSL helper leg (false = narrow-rule/mirrored end state) |
| `brain_mode` | `auto` | `auto` = systemd unit if installed, else root-less process spawn |
| `brain_port` | `8765` | main only; instances derive from `RAPHAEL_INSTANCE` |

## Contract sync (requests filed, AGENT_RULES §2)

- `docs/requests/infra__to__integrator__protocol-loopback-bind.md` —
  PROTOCOL §1/§"WSL IP churn" wording + `config.yaml server.host` comment
  follow the loopback default.
- `docs/requests/infra__to__integrator__pidfile-location.md` —
  INTERFACES §d pidfile column: `~/.raphael[/instance]/brain.pid`.
- `docs/requests/infra__to__brain-core__pidfile-location.md` —
  `brain/app.py` honors `RAPHAEL_PIDFILE` (exported by the supervisor).

## Mini-PC / LAN move — service endpoints (Wave 5U §5.7, task 5, P3)

Goal: one Brain on a small always-on box, Body/Orb/chat on other devices —
**without weakening today's posture.**

| surface | today (laptop, loopback) | on the move |
|---|---|---|
| Brain HTTP/WS | `server.host: 127.0.0.1` (`config.yaml:21`) + `supervisor.ws_url: ws://127.0.0.1:8765/ws` | Brain stays `127.0.0.1` on the mini-PC **by default**; exposing it = explicit `RAPHAEL_BIND`/`server.host` change on a PRIVATE LAN only, never 0.0.0.0 on shared networks |
| Body → Brain | `body/win/instance.py::ws_url()` derives `ws://127.0.0.1:<port>/ws` (loopback, instance-derived) | needs a host: proposed config key **`brain.url`** (single source for body + orb; integrator key — proposal in `docs/requests/infra__to__integrator__brain-url-key.md`) until it exists: per-host `RAPHAEL_...` env on that device |
| Orb → Brain | same ws_url derivation (WSL side) | same `brain.url` story |
| Chat UI | `http://127.0.0.1:<port>/chat` (same origin as `/ws`) | `http(s)://<brain-host>:<port>/chat` — token-gated like everything else |
| Transport | plain HTTP/WS on loopback (no TLS needed) | **TLS required off-box**: terminate at a reverse proxy (caddy/nginx, local CA or real cert) or tailscale/wireguard mesh — plaintext WS on a LAN carries the token in the clear |
| Token | `%APPDATA%\Raphael\token` / `~/.raphael/token`, header `X-Raphael-Token` (or Bearer) | unchanged: every endpoint (REST + WS `auth` frame) still demands it; keep files mode 600 per device |
| Firewall | narrow Hyper-V rule `scripts/win/allow-brain-localhost.ps1` (TCP 8765, WSL creator only) | OS firewall: allow TCP 8765 **only** from the trusted LAN range / tunnel interface — never a profile-wide allow |

Rules that do not change: loopback default (`server.host: 127.0.0.1`),
fail-closed privacy gates, token-on-every-endpoint, value-blind logs.
Moving to the mini-PC is a *documented opt-in* per line above — each row
says what flips and what never does.
