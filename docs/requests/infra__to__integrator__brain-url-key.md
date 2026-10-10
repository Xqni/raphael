# infra → integrator: brain-url-key
Status: OPEN

## What

New integrator-owned config key **`brain.url`** (default
`http://127.0.0.1:8765`, plus `brain.ws_url` if you prefer one key
`brain.url` → derived ws): the single place where Body/Orb/CLI learn the
Brain's address, replacing the hardcoded `ws://127.0.0.1:<port>/ws` in
`body/win/instance.py::ws_url()` and friends for the mini-PC/LAN move.

I documented the full surface in `scripts/NETWORK-SECURITY.md` ("Mini-PC /
LAN move" table) per §5.7 task 5 — the doc is DONE either way; the KEY is
yours to add (config.yaml + the env override `RAPHAEL_BRAIN_URL` for
per-device instances). Consumers (body/orb/ws_url) then read it — those
files belong to pc-control/orb, so the request fans out from you.

## Why

Every consumer currently derives loopback-only from the instance PORT; a
moved Brain needs a host without breaking the loopback default or the
fail-closed posture (TLS required off-box, token unchanged, no broad
firewall — same doc).

## Impact

One key + one env override; defaults keep today's behavior byte-identical
(`127.0.0.1`). Until it lands, the doc's per-device env note applies.
