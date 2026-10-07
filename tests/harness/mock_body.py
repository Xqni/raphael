"""Mock Body (PROTOCOL §3/§4/§7): role=body session that receives act_req
frames and answers them with scripted act_res handlers.

Script behaviors (per successive act_req, default 'ok'):
- 'ok'                       -> act_res{ok: true, result: "mock body ok: <action>"}
- {'ok': False, 'error': ...} -> act_res{ok: False, error} (+ optional fields)
- 'drop'                     -> no reply (models a dead Body; the Brain's
                                act timeout path handles it)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .wssession import WSSession


class MockBody(WSSession):
    role = 'body'
    client_name = 'body-mock'

    def __init__(self, client, token: str, script: Optional[List[Any]] = None,
                 **kwargs):
        super().__init__(client, token, **kwargs)
        self.script: List[Any] = list(script or [])
        self.act_reqs: List[Dict[str, Any]] = []
        self.replies: List[Dict[str, Any]] = []

    def next_act_req(self, timeout: float = 10.0) -> Dict[str, Any]:
        """Wait for the next act_req, apply the scripted behavior, return it."""
        frame = self.wait(lambda m: m.get('type') == 'act_req', timeout=timeout)
        self.act_reqs.append(frame)
        behavior = self.script.pop(0) if self.script else 'ok'
        if behavior == 'drop':
            return frame
        if behavior == 'ok':
            self.reply(frame, ok=True,
                       result=f"mock body ok: {frame.get('action')}")
        elif isinstance(behavior, dict):
            self.reply(frame, **behavior)
        else:  # pragma: no cover - guard against bad test scripts
            raise ValueError(f'unknown act_req behavior: {behavior!r}')
        return frame

    def reply(self, frame: Dict[str, Any], ok: bool = True,
              result: Any = None, error: Optional[str] = None,
              **extra) -> None:
        res = {'type': 'act_res', 'v': 1, 'job': frame.get('job'),
               'ok': bool(ok), **extra}
        if result is not None:
            res['result'] = result
        if error is not None:
            res['error'] = error
        self.replies.append(res)
        self.send(res)
