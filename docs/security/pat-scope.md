# GitHub token scope — SEC-4 (human-applied)

> **This is a HUMAN action.** Raphael never creates, reads, edits, or rotates this
> token — she only checks its *presence* (value-blind) and, once you approve a
> push, uses it through `gh`. Apply it yourself in the GitHub UI; the packet
> (`docs/audit-tasks/tools-memory.md`, SEC-4) is the source requirement.

## The token (fine-grained Personal Access Token)

| Setting | Value | Why |
|---|---|---|
| Type | **Fine-grained PAT** (NOT classic — classic tokens are repo-wide) | per-repo scoping |
| Repository access | **Selected repositories ONLY** — exactly `<gh-owner>/raphael` (addendum §9 build repo) | nothing else is reachable, even with a leaked token |
| Contents | **Read & write** | `git push` after your confirmation |
| Actions | **Read & write** | read run status; re-run/dispatch the CI workflows (`ci.yml`, `tests-heavy.yml`, QA-4) |
| Pull requests | **Read & write** | PR creation/comments from the build pipeline |
| Administration | **NO** (omit the permission entirely) | visibility changes + repo creation need it — see "what Raphael cannot do" |
| Organization permissions | **NONE** (account-level token only; no org grants) | no org blast radius |
| Expiry | **≤ 90 days** (GitHub maximum for fine-grained is 1 year; pick 90) | limits leak window |
| Account permissions | none beyond defaults | — |

## What Raphael CANNOT do with it (by construction, SEC-4)

Verified against GitHub's official docs (*Permissions required for fine-grained
personal access tokens*): **`POST/user/repos` (create) and `repo edit
--visibility` both require `Administration: write`.** Our PAT has no
Administration scope, therefore:

- **repo creation = your action.** Create the repo yourself (always **private**)
  in the GitHub UI → it appears under the token's *Selected repositories* →
  Raphael can then push to it.
- **visibility changes are refused entirely** — the `github_set_visibility`
  tool was REMOVED (it would have required Administration). Public creation
  (`github_create_repo_public`) also removed. Repo deletion / settings changes:
  no tool ever existed (grep-verified in the audit).
- `github_push` remains **confirm-gated in code** (`risky=True` in the registry;
  `brain/confirm.py` pattern-matches `push` as publish) — every push asks you
  first, timeout fails closed (ABORT).

## Token hygiene (enforced in code + required of you)

- **Presence checks only**: `github_status` prints `GITHUB_TOKEN/GH_TOKEN: set |
  MISSING` — never the value (`brain/tools/github/__init__.py`, `_have_token`).
- **Output scrubbing**: every `gh`/`git` output passes `_scrub()` which masks
  `ghp_/gho_/ghu_/ghs_/ghr_…`, `github_pat_…`, `AKIA…` shapes → tool output and
  logs can never carry the token.
- The token lives in `.env` (chmod 600, git-ignored) — never in chat, prompts,
  notes, or this repo's history (AGENT_RULES §7).
- **Rotation steps (every ≤90 days, or immediately if suspected leak):**
  1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained.
  2. **Generate new token** with the exact table above (same selected repo).
  3. Update `GITHUB_TOKEN` in the laptop's `.env` (chmod 600) — presence-check
     with `github_status` (it must say `set`; the value is never displayed).
  4. **Revoke the old token** (Delete) — only after the new one verifies.
  5. Note the rotation date in `docs/PAID_USAGE.md`/ATTENTION for the record.
  6. Revoke immediately (any time) if you suspect exposure: same page → Revoke.

## Value-blind presence checker (optional, already landed)

`github_status` (registry tool, `risky=False`) is exactly the packet's
"value-blind PAT-presence checker": gh/git path presence, token `set`/`MISSING`,
`default_visibility: private`, `auto_public: False`, and the SEC-4 note that
creation/visibility are human actions. It never invokes the API, never touches
the value.
