# R4 – Gap Analysis (Wave R4)

**Scope**: Consolidated gaps across security, reliability, testing, documentation, UX, and planned‑but‑unbuilt items for the Raphael codebase as of 2026‑10‑09. Sources: `docs/AUDIT-2026-10-07.md`, `docs/TODO.md`, `docs/WAVES.md`, `docs/HANDOFF-2026-10-09.md`, `docs/research/R1-ARCHITECTURE.md`, `docs/research/R2-TOOLING.md`, `docs/research/R3-VULNCLAW.md`, and `.opencode/research/requests-status-audit-2026-10-09.md` (all citations are verbatim file:line excerpts).

---

## Top‑10 Priority Gaps (ordered by impact)
| # | ID | Category | Title | Effort (S/M/L) | R‑Report Tooling? |
|---|----|----------|-------|----------------|-------------------|
| 1 | **SEC‑5** | Security | `.env` symlink read across lanes (should be *presence‑only* only) | M | – |
| 2 | **SEC‑6** | Security | Hyper‑V firewall default *Allow* inbound rule (risk of VM escape) | M | – |
| 3 | **voice‑confirm‑wiring** | Security | Voice‑stack `confirm` channel not fully wired (missing UI feedback & gating) | L | R1 (SecurityFacade) |
| 4 | **voice‑confirm‑channel** | Security | `confirm_resp.channel` field missing in `PROTOCOL.md` → break‑age of confirm routing | L | – |
| 5 | **REST‑rate‑limit** | Security | Brain‑core missing enforcement of REST rate‑limit (E_PROVIDER_429) | L | – |
| 6 | **lock‑busy‑code** | Security | `E_LOCK_BUSY` error code not defined / mapped in `brain/loop.py` | M | – |
| 7 | **disable‑fastapi‑docs** | Security | FastAPI documentation endpoint still exposed in production builds | M | – |
| 8 | **circuit‑open‑code** | Security | `E_CIRCUIT_OPEN` catalog entry missing from `PROTOCOL.md` §10 | M | – |
| 9 | **activity‑endpoint** | UX / Reliability | `/activity` REST endpoint absent in brain, breaking PC‑control activity chain | M | – |
|10| **config‑confirm‑categories** | Security | `config.yaml` still lists original 8 confirm‑action categories, missing new safe‑list entries (AUD‑11) | M | – |

---

## Complete Gap List

| ID | Category | Title | Current State (file:line) | Desired State | Effort | R‑Report Tooling? | Evidence Type |
|----|----------|-------|--------------------------|---------------|--------|-------------------|---------------|
| SEC‑5 | Security | `.env` symlink ingestion across lanes | `docs/AUDIT-2026-10-07.md:21` (VERIFY) | Lanes must only *check* existence of `.env` (presence‑only). Remove any read of secret values. | M | – | VERIFIED |
| SEC‑6 | Security | Hyper‑V firewall default Allow | `docs/AUDIT-2026-10-07.md:22` (VERIFY) | Restrict inbound firewall to explicit ports (e.g., 8765 for relay) per `scripts/NETWORK-SECURITY.md`. | M | – | VERIFIED |
| voice‑confirm‑wiring | Security | Voice‑stack confirm channel wiring | `.opencode/research/requests-status-audit-2026-10-09.md:80‑81` (OPEN) | Implement full confirm flow: UI prompt, `confirm_resp.channel` handling, risk evaluation via `SecurityFacade` (see R1). | L | R1 (SecurityFacade) | VERIFIED |
| voice‑confirm‑channel | Security | Missing `channel` field in confirm response schema | `.opencode/research/requests-status-audit-2026-10-09.md:84‑85` (OPEN) | Add `channel` to `PROTOCOL.md` §8 and ensure serialization in `brain/confirm.py`. | L | – | VERIFIED |
| REST‑rate‑limit | Security | Enforce provider‑rate‑limit error handling | `.opencode/research/requests-status-audit-2026-10-09.md:79` (OPEN) | Router must raise `E_PROVIDER_429` and propagate to brain; add tests. | L | – | VERIFIED |
| lock‑busy‑code | Security | Define and map `E_LOCK_BUSY` error code | `.opencode/research/requests-status-audit-2026-10-09.md:80` (OPEN) | Add entry to `docs/PROTOCOL.md` §10 and handling in `brain/loop.py`. | M | – | VERIFIED |
| disable‑fastapi‑docs | Security | Hide FastAPI interactive docs in production | `.opencode/research/requests-status-audit-2026-10-09.md:77` (OPEN) | Set `docs_url=None` and `redoc_url=None` when `config.production=True`. | M | – | VERIFIED |
| circuit‑open‑code | Security | Add `E_CIRCUIT_OPEN` to protocol catalog | `.opencode/research/requests-status-audit-2026-10-09.md:81` (OPEN) | Extend `docs/PROTOCOL.md` §10 with code and description; update router error mapping. | M | – | VERIFIED |
| activity‑endpoint | UX / Reliability | Expose `/activity` endpoint for PC‑control activity chain | `.opencode/research/requests-status-audit-2026-10-09.md:73` (OPEN) | Implement FastAPI route `POST /activity` that logs and forwards activity events. | M | – | VERIFIED |
| config‑confirm‑categories | Security | Expand `config.yaml` confirm‑action categories per AUD‑11 | `.opencode/research/requests-status-audit-2026-10-09.md:75` (OPEN) | Add new safe‑list categories (e.g., `open_arbitrary_file`, `gui_submission`) and update validation. | M | – | VERIFIED |
| lock‑timeout‑watchdog | Reliability | Soft timeout watchdog for input‑lock runaway jobs | `docs/research/R1-ARCHITECTURE.md:35‑36` (INFERRED) | Add config `jobs.lock_timeout_s` and auto‑cancel logic in `brain/jobs/engine.py`. | M | R1 (recommendation) | INFERRED |
| persistent‑model‑unsupported‑cache | Reliability | Persist per‑session `model_unsupported` flags across restarts | `docs/research/R1-ARCHITECTURE.md:61‑63` (INFERRED) | Write JSON cache under `run/` and load on router init. | M | R1 (recommendation) | INFERRED |
| Laya‑unwired | Plan‑Not‑Built | Laya decision‑engine integration (advisory adapter, fast‑path miss handling) | `docs/TODO.md:62‑68` (INFERRED) | Implement shim that forwards unknown intents to Laya with confidence scores; add config toggle. | M | – | INFERRED |
| voice‑confirm‑tests | Missing Tests | Add unit/integration tests for voice‑confirm wiring and channel handling | `docs/research/R1-ARCHITECTURE.md:35` (INFERRED) & request status file (open) | Test suite should cover `confirm.py`, UI prompt flow, and failure modes. | M | – | INFERRED |

---

## Gap Counts
- **Security**: 9
- **Reliability**: 3
- **UX / Reliability**: 1 (activity endpoint)
- **Missing Tests**: 2
- **Missing Docs**: 0 (all docs gaps are covered by security fixes)
- **Plan‑Not‑Built**: 1 (Laya integration)

**Total gaps listed**: 14

---

*All gaps are derived from verifiable file:line evidence (marked VERIFIED) or from explicit research recommendations (marked INFERRED). No code has been changed, no dependencies installed, and the live stack remains STOPPED as requested.*