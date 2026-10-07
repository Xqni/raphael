# pc-control → integrator: instance-token-path
Status: OPEN

## What
Derive the token path from `RAPHAEL_INSTANCE` in `brain/auth.py` (integrator-
owned, Core Guard-adjacent), so an isolated instance reads ITS token instead
of the main one. Exact proposed behavior:

| RAPHAEL_INSTANCE | token files searched |
|---|---|
| unset / `main` | `RAPHAEL_TOKEN_PATH` → `%APPDATA%\Raphael\token` → `~/.raphael/token` (today, unchanged) |
| `<lane>` | `RAPHAEL_TOKEN_PATH` → `%APPDATA%\Raphael\<lane>\token` → `~/.raphael/<lane>/token` |

Sketch (for review only; `main` path resolution identical to today):

```python
def get_token():
    path = os.environ.get('RAPHAEL_TOKEN_PATH')
    if not path:
        name = os.environ.get('RAPHAEL_INSTANCE', '').strip() or 'main'
        root = pathlib.Path.home() / '.raphael'
        path = str(root / 'token' if name == 'main' else root / name / 'token')
    ...
```

The Body side already follows exactly this table
(`body/win/instance.py::token_candidates`, implemented this wave), so Body
and Brain agree per instance; a lane body can never authenticate with (or be
authenticated against) the main token.

## Why
AGENT_RULES §5 + INTERFACES §d: instances must not share secrets. Without
this, an instance Brain (started with `RAPHAEL_INSTANCE=pc-control`) still
validates against `~/.raphael/token` — the MAIN token — so either auth fails
(lane body uses `~/.raphael/pc-control/token`) or, worse, both stacks share
one credential. Wave 2 exit testing on an isolated instance needs both sides
agreed.

## Impact
- `brain/auth.py` edit = integrator-only (auth is Core Guard); semantics for
  `main` are byte-for-byte unchanged — zero impact on the live stack.
- Tests: pc-control covers the body half (`body/win/tests/test_pc_instance.py`);
  the auth half needs a brain-side test next to the existing RAPHAEL_TOKEN_PATH
  fixture pattern (qa-security / integrator).
