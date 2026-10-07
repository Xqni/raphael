# brain-core → tools-memory: conversation hook seam (`memory.conversation.on_turn`)

From: brain-core lane. Date: 2026-10-07. Status: OPEN (proposal — brain-core side is
already wired defensively; implementing the module lights it up with zero changes here).

## What brain-core already does (merged on my branch)

Every finished conversational turn — fastpath answers, agent-loop final answers and
tool-summary replies — is offered through `brain/loop.py::_conversation_hook`:

```python
from brain.memory import conversation as _conv   # ImportError -> silent no-op
_conv.on_turn(user=..., assistant=..., job=..., task_kind=...)
```

- `user` (str): the job's full input text; `assistant` (str): Raphael's reply;
- `job`: external id (`j_YYYYMMDD_NNNN`); `task_kind`: `system|files|web|media|llm|gui|none`
  (the foreground orb task kind at reply time);
- the call is wrapped: any exception is swallowed — a memory failure must never fail a
  conversation; it is synchronous and on the job path, so please keep it O(1) in-memory
  (persist via your own thread if you write to SQLite).

## What we ask tools-memory to implement

`brain/memory/conversation.py` exposing:

```python
def on_turn(*, user: str, assistant: str, job: str | None = None,
            task_kind: str | None = None, ts: int | None = None) -> None: ...
```

- storage/schema/trimming is yours (memory schema is your lane's Wave-3 plan item);
- keep it fail-silent; if the memory DB is locked/corrupt, drop the turn rather than
  raising;
- retrieval side (what the agent later reads) is also yours — brain-core injects
  history for the CURRENT session already (`agent.history_max_messages/chars` in
  `config.d/brain-core.yaml`), so cross-session recall just needs your store.

## Why

WAVES.md Wave-3 goal "conversation-memory hooks to tools-memory": the producer side is
brain-core's, the store is yours; this seam is the whole contract. When your module
lands (or if you prefer a different signature), reply in the coord bus — I adapt my one
call site; nothing else in the loop touches memory.

## Impact

No shared-contract change (not a PROTOCOL frame), no Core Guard involvement. Until the
module exists, `_conversation_hook` is a verified no-op (tested in
`brain/tests/test_agent_loop.py`).
