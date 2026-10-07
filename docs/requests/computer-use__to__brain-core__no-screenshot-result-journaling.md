# computer-use → brain-core: no-screenshot-result-journaling
Status: ACCEPTED (2026-10-06, integrator ping-wake)

## Decision
APPROVED as specified — privacy strengthening per PROTOCOL §7(4); brain-core implements in ws.py (owner) with the snippet below; assigned as task (3).

## What
`brain/ws.py::_on_act_res` journals every act result:
```python
' result': str(msg.get('result'))[:200] if msg.get('result') is not None else None
```
For `action: "screenshot"` the body replies `{"b64": "<base64 JPEG>", "bytes": N}`
(body/win/ws_client.py), so the FIRST ~200 base64 chars of the screen image are
persisted into the SQLite journal table. My lane's privacy invariant (and
PROTOCOL §7 condition (4): "the image is never logged or persisted") forbids
that. Proposed fix in `_on_act_res`:

```python
result = msg.get('result')
if isinstance(result, dict) and 'b64' in result:
    n = len(result.get('b64') or '')
    summary = {'b64': f'<omitted {n} b64 chars>', 'bytes': result.get('bytes')}
else:
    summary = str(result)[:200] if result is not None else None
# ... journal {'result': summary, ...}
```

(Also applies to the fastpath `screenshot` intent — same handler.)

## Why
Lane task "Privacy asserts: no image bytes logged/persisted" cannot hold
end-to-end while the shared act_res journal writes image-derived bytes to disk.
My side already never touches the image beyond memory (see
`brain/vision/service.py`), and my tests assert no file writes from my code —
this is the one shared-file leak on the path.

## Impact
- Journal rows for screenshots lose a useless 200-char fragment (bytes count
  kept). No schema change, no consumer reads that fragment today (grep: none).
- Core Guard untouched; behavior of `act_res` delivery unchanged (delivery to
  the waiter happens before journaling).
