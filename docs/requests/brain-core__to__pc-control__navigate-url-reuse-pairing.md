# brain-core → pc-control: navigate-url-reuse-pairing
Status: OPEN — awaiting pc-control (Wave 5P UX pairing, coord decision 2026-10-10)

## What

Coord decision (2026-10-10, pairing with your P0): fastpath/LLM tool mapping
must prefer REUSE for `open <site>` / `search <q>` when a browser is already
running — your navigate-in-place (foreground Ctrl+L+URL+Enter through the
input lock). First-open stays `launch_url` / `open_app`.

**Proposed tool name: `navigate_url`** (parallel to your `launch_url`),
args `{"url": "<absolute http(s) URL>"}`, category `gui` (act_req pipeline
like launch_url), not risky (reversible navigation). My side is ALREADY
merged-ready against this name:

- `brain/fastpath.py`: browser-foreground detection (fresh pushed identity
  `title | process` — process half exact-match `chrome/msedge/firefox/brave/
  opera/vivaldi/chromium`; title half suffix/suffix-dashed match) + registry
  probe; repeat open → `navigate_url {url}`; repeat search (incl. the
  `open youtube and search X` compound) → `navigate_url` to the YouTube
  results URL, user-facing text unchanged.
- **Safe pairing window:** while `navigate_url` is NOT in the registry, the
  mapping falls back to today's `launch_url`/`search_youtube` — you can land
  your half whenever; nothing breaks either way.

## Asks (pc-control side)

1. **Confirm the name `navigate_url`** (or reply with your preferred name —
   my mapping switches on the exact registry name; one-line change here).
2. Land the tool: foreground Ctrl+L+URL+Enter through the input lock, same
   act_req shape as launch_url.
3. Tool-choice docs (LLM half): update the `launch_url`/`search_youtube`
   spec descriptions in `brain/tools/pc/launch.py` (YOUR files) to steer the
   model — "if the user may already have a browser open (check
   list_running_apps), prefer navigate_url over launch_url". Fastpath handles
   the deterministic case; the spec text covers model-picked calls.

## Evidence (brain-core, 2026-10-10)

- `brain/tests/test_fastpath_open_search.py` 13/13 (8 new reuse fixtures:
  repeat-open→navigate, first-open→launch, unregistered→fallback, title-only
  identity, non-browser foreground, ambiguous-title separator guard,
  search+compound→results URL); brain suite 257 passed.
