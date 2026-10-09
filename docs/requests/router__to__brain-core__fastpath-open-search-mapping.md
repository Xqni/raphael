# router → brain-core: fastpath open+search mapping (Wave-2 Bug B, router half)
Status: OPEN

## Status update (integrator freshness pass 2026-10-09)
ANSWERED/DONE — evidence: the proposed mapping landed near-verbatim — `brain/fastpath.py:135` `_search` intent, registrations at `:194-198` (`register_intent('search ' / 'search for ' / 'youtube ', _search)` with the comment "Bug B (router request APPROVED): explicit search intents"), and the "open youtube and search …" redirect in `_open` (comment at :116 cites the live-gate failure). Existing branches preserved per proposal.

## What
Exact proposed change to `brain/fastpath.py` (brain-core-owned file — AGENT_RULES §2:
I propose, you implement; I never edit it). Today `_open` sends the WHOLE phrase to
`open_app`, so the live gate command fails:

```python
# BEFORE (brain/fastpath.py:101-111)
def _open(text, ctx):
    arg = text[5:].strip()  # after 'open '
    if not arg:
        return None
    if ' ' not in arg and '.' in arg:
        url = arg if '://' in arg else 'https://' + arg
        return IntentResult(text=f'Opening {arg}…',
                            tool='launch_url', tool_args={'url': url},
                            task_kind='web')
    return IntentResult(text=f'Opening {arg}…',
                        tool='open_app', tool_args={'name': arg},   # <- "YouTube and search lo-fi"
                        task_kind='system')
```

Proposed (adds `import re` at module top; keeps every existing branch intact):

```python
def _open(text, ctx):
    arg = text[5:].strip()  # after 'open '
    if not arg:
        return None
    # Wave-2 Bug B: "open youtube and search lo-fi" is a YOUTUBE SEARCH
    m = re.match(r'^(?P<site>.+?)\s+and\s+search\s+(?P<query>.+)$', arg,
                 re.IGNORECASE)
    if m and 'youtube' in m.group('site').lower():
        query = m.group('query').strip()
        return IntentResult(text=f'Searching YouTube for {query}…',
                            tool='search_youtube', tool_args={'query': query},
                            task_kind='web')
    if ' ' not in arg and '.' in arg:
        url = arg if '://' in arg else 'https://' + arg
        return IntentResult(text=f'Opening {arg}…',
                            tool='launch_url', tool_args={'url': url},
                            task_kind='web')
    return IntentResult(text=f'Opening {arg}…',
                        tool='open_app', tool_args={'name': arg},
                        task_kind='system')


def _search(text, ctx):                      # NEW intent — docstring already promises it
    q = re.sub(r'^(?:search(?:\s+for)?|youtube\s+search)\s+', '', text.strip(),
               flags=re.IGNORECASE)
    q = re.sub(r'\s+on\s+youtube\.?$', '', q, flags=re.IGNORECASE).strip()
    if not q:
        return None
    return IntentResult(text=f'Searching YouTube for {q}…',
                        tool='search_youtube', tool_args={'query': q},
                        task_kind='web')
```
plus registration in `register_builtin_intents()`:
```python
    register_intent('search ', _search)
    register_intent('search for ', _search)
    register_intent('youtube ', _search)
```

Suggested unit tests (your folder, `brain/tests/`):
- `run_intent('open youtube and search lo-fi', ctx)` → tool `search_youtube`,
  args `{'query': 'lo-fi'}`, narration "Searching YouTube for lo-fi…"
- `run_intent('search lo-fi', ctx)` and `run_intent('search for lo-fi on youtube', ctx)`
  → `search_youtube` with `{'query': 'lo-fi'}`
- `run_intent('open chrome', ctx)` → still `open_app`; `run_intent('open youtube.com', ctx)`
  → still `launch_url` (dot-without-space branch untouched)
- `run_intent('open settings', ctx)` unchanged (Windows Settings → open_app).

## Why
`docs/BUGS-WAVE2.md` Bug B: Wave-2 exit criterion 1 **FAIL** — live job
`j_20261007_0033` ran `open_app{name:"YouTube and search lo-fi"}`, body spawned a cmd
window (blank flash, user-visible) and failed with no `act_res`. Dossier assigns
"router owns the intent→tool mapping", but the mapping code lives in your
`brain/fastpath.py`, so the actual edit is yours (I have no write authority there).

## Impact
No shared-contract change (PROTOCOL §7 already allow-lists `search_youtube{query}`;
`brain/tools/pc/launch.py` + `brain/tools/computer_use/runner.py` already implement it).
pc-control separately owns body-side `open_app` robustness + `act_res` error surfacing
(the blank-window/no-act_res half) — not part of this request.
