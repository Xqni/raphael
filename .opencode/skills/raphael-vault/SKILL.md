---
name: raphael-vault
description: Raphael's own Obsidian vault — her persona canon, memory journal, and session log. Use when acting as/for Raphael: reading her identity/service-model spec, appending a journal entry, or deciding what knowledge belongs in the vault vs the repo. Covers paths, layout, and write rules.
---

# raphael-vault skill

Raphael's personal Obsidian vault: the `vault/` directory at the REPO ROOT (gitignored — her living memory; the persona canon is pushed under `docs/research/persona/`). The REPO
(`<repo-root>`) stays the source of truth for code and process; the VAULT is the
source of truth for persona and memory. This is separate from the damianqt pipeline vault
(`C:\<win-user>\damianqt-vault` — YouTube/comics sessions own that; never cross-write).

## Paths (recorded once — never guess again)

- Vault location: `<repo-root>/vault` (untracked by git on purpose)
- Open in Obsidian (Windows) via the `\wsl.localhost\Ubuntu-26.04` share, or any editor on the WSL side.

## Layout

- `README.md` — the map + rules (source of truth for paths).
- `persona/00-CONSOLIDATED-BRIEF.md` — canonical persona spec: lineage
  (Great Sage → Raphael → Ciel), service model, autonomy rules, tier mapping, voice/tone
  spec, and the **binding debunked-claims register** (Raziel, VA "Setoguchi",
  "Hollow Mixture", phantom arc names — never assert these).
- `persona/01-…05-….md` — the five vetted research reports (profile, service, Ciel,
  canon map, portrayal/TTS).
- `journal.md` — append-only session log.

## When to write

- **Journal entry** when the user says "log it" / "review", after a major milestone, or
  when persona/identity decisions are made. Format: dated section on top
  (`## YYYY-MM-DD — title`), short mechanical bullets (what happened, decisions, open
  threads). Append-only — never rewrite history.
- **Persona docs** are updated ONLY from canon-vetted research (double-sourced), and the
  repo copies under `docs/research/persona/` stay the upstream — refresh both together.

## Hard rules

- **No secrets, ever**: no tokens, keys, usernames, home paths. Placeholders:
  `<wsl-user>`, `<win-user>`, `<gh-owner>`, `<repo-root>`.
- Never copy YouTube/comics pipeline files here (or vice versa).
- If a file's home is ambiguous: code/process → repo; persona/memory → vault.
