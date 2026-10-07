# config.d/ — per-lane config fragments (loader contract: docs/INTERFACES.md §c)

- One file per lane: `config.d/<lane>.yaml` — **your lane's file only**.
- Load order: `config.yaml` base → `config.d/*.yaml` (filename-sorted, deep-merged: mappings merge, lists/scalars replace) → active profile overlay (`profiles.<profile>`) → instance env overrides.
- Secrets never go here — `.env` only.
- `config.yaml` base and the `profiles:` block are integrator-owned; propose changes via `docs/requests/`.
- The loader is built by the brain-core lane; until it lands, fragments are inert (base already carries the effective `cloud_temp` values).
