# orb → brain-core: orb-state-transitions

Status: OPEN

## What

`brain/ws.py::refresh_orb_state()` (lines 249-273) and `_on_state_req()`
(lines 529-547) can only ever emit FOUR base states, and they hardcode the
job-specific fields. Proposed change:

```python
# before (brain/ws.py:255-270)
if st.get('jobs_pending_confirm'):
    state = 'confirm'
elif st.get('paused'):
    state = 'idle'          # paused is a MODE overlay, not an orb state
elif st.get('jobs_active'):
    state = 'thinking'
else:
    state = 'idle'
if mode.private and state in ('idle',):
    state = 'private_overlay'
frame = {
    'type': 'orb_state', 'v': 1, 'state': state,
    'jobs_active': st.get('jobs_active', 0),
    'mode': mode.label(),
    'shape_hint': 'circle', 'task_kind': 'none',
}
```

`listening`, `speaking`, `acting`, `error`, `starting` are never sent, and
`shape_hint` / `task_kind` / `provider` / `model` are constant. Per
INTERFACES §e the Brain should emit, at minimum:

| state | trigger (INTERFACES §e) | emitted today |
|---|---|---|
| `starting` | boot snapshot while engine not ready | **no** |
| `idle` | initial snapshot / last job terminal | yes |
| `listening` | mic lane `audio_start` (reason `wake`\|`ptt`) | **no** — `_on_audio_start` (ws.py:592) sends only an `ack` |
| `thinking` | job_event `running`, stage `routing`\|`llm` | yes (coarse: any active job) |
| `acting` | first `act_req` sent (stage `tool`) | **no** |
| `speaking` | first `speak` `start` event | **no** — loop.py:88-103 streams `speak` but never refreshes `orb_state` |
| `confirm` | `needs_confirm` / `awaiting_confirm` | yes |
| `error` | job `failed`, auth failure, chain exhausted | **no** |
| `mode: paused` | control pause/resume | yes (`mode`) |
| `mode: private` | control private_on/off | yes (`mode`) |

Plus the fields INTERFACES §e requires on every frame:

- `shape_hint`: real value from `config.yaml → orb.shape_map` for the current
  foreground job's `task_kind` (today always `'circle'`).
- `task_kind`: the foreground job's kind (today always `'none'`).
- `provider`, `model`: router's current/last target (today absent).
- `amplitude` *(optional, see below)*: 0..1 mic RMS while `state=='listening'`,
  so the orb's listening reactivity has a source.

Concretely:

1. `_on_audio_start` → `hub.broadcast(orb_state(state='listening', ...))`;
   `audio_end` (no job yet) → back to `idle`.
2. loop.py: on `voice.speak(...)` first `event == 'start'` → `state='speaking'`;
   after `event == 'end'` + pending jobs → `thinking`, else `idle`.
3. on the first `act_req` for a job → `state='acting'` (hold while any
   input-lock job holds the lock).
4. job `failed` / router chain exhausted → transient `error`, then `idle`.
5. boot snapshot while the engine is not ready → `starting`.
6. `refresh_orb_state()` should take the shape/task/provider/model from the
   current foreground job instead of the literals.

## Why

Wave 2 exit criterion 4 is *"Per-state orb screenshots prove distinct visuals"*,
and docs/lanes/orb.md W2.2 is *"full state mapping per docs/PROTOCOL §8"*.

The orb lane's end-to-end frame trace (`body/orb/test/orb-trace.cjs`,
evidence in `docs/orb/trace/trace.jsonl`) proves the client side is NOT the
bottleneck: with a mock Brain replaying the full sequence, every state reaches
the renderer, the state name matches, and the layer weights / GL uniforms move
with it. What the real Brain can say is `idle | thinking | confirm |
private_overlay` only — so in production the orb sits on two near-identical
looks (idle vs thinking) all day, which is exactly the reported symptom
*"the orb's graphics do not change between states"*.

Frame-trace evidence (real code, read-only audit):

- `brain/ws.py:249-273` `refresh_orb_state()` — the four-state ladder above.
- `brain/ws.py:529-547` `_on_state_req()` — duplicate of the same ladder.
- `brain/ws.py:592-606` `_on_audio_start()` — no `orb_state` broadcast.
- `brain/loop.py:88-103` — `speak` fan-out to `body`+`ui`, no `orb_state`.
- `brain/app.py:41` `engine.on_state = lambda frame: hub.refresh_orb_state()`
  — every `job_event` re-runs the ladder, but the ladder has no other answers.

The orb has already been fixed to render all of them (mode overlays, jobs
dots, shape morphs, amplitude); this request is only about EMISSION.

## Impact

- Touches `brain/ws.py`, `brain/loop.py` (brain-core lane, not the orb's).
- No shared contract change: every emitted value is already legal per
  PROTOCOL §8 / INTERFACES §e; the orb accepts all of them today.
- No Core Guard impact (AGENT_RULES §8) — no auth/pause/private/confirm
  semantics change; this only adds display frames.
- Risk: extra `orb_state` frames. They are small (<200 B) and only on
  transitions, well inside the 40 msgs/s per-connection limit (PROTOCOL §1).
- Until this lands, the orb renders `starting/idle/thinking/acting/speaking/
  confirm/error/reconnecting/offline` correctly when told, and the mock-brain
  trace harness keeps proving it.
