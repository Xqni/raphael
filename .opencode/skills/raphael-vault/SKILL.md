---
name: raphael-vault
description: Raphael's own Obsidian vault — her persona canon, memory journal, and session log. Use when acting as/for Raphael: reading her identity/service-model spec, appending a journal entry, or deciding what knowledge belongs in the vault vs the repo. Covers paths, layout, and write rules.
---

# raphael-vault skill

Raphael's personal Obsidian vault: persona canon + memory journal. The REPO
(`/home/dami/raphael`) stays the source of truth for code and process; the VAULT is the
source of truth for persona and memory. This is separate from the damianqt pipeline vault
(`C:\Users\jxesu\damianqt-vault` — YouTube/comics sessions own that; never cross-write).

## Paths (recorded once — never guess again)

- Obsidian (Windows): `C:\Users\jxesu\raphael-vault`
- WSL (tools live here): `/mnt/c/Users/jxesu/raphael-vault`

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
