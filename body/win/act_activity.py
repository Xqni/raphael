"""`activity` act — F-3 undoable-act journal (query + undo).

§7 request: docs/requests/pc-control__to__integrator__protocol-activity-act.md
(pending tracked in actions.PENDING_PROTO_ADDITIONS). The orb/CLI consume the
same journal through brain-core's relay (…__brain-core__activity-endpoint.md);
the schema lives in body/win/journal.py (co-share doc …__orb__activity-
viewer-schema.md).

ops:
* list {op, limit?}  — newest-first journal entries (undone flags folded in).
* undo {op, seq?}    — invert the newest undoable entry, or a specific seq.
  Inverse applies FIRST; only success marks the entry undone (journal never
  lies). No confirmation bypass: journaling adds nothing to AGENT_RULES §8 —
  acts keep their existing risky/confirm metadata.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

try:
    from . import journal
    from .actions import (offload,
ActionError, opt_enum, opt_int, reject_extra,
                          register_action
)
except ImportError:  # script mode
    import journal
    from actions import (ActionError, opt_enum, opt_int, reject_extra,
                         register_action)

_OPS = {'list', 'undo'}


def _validate_activity(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'op', 'limit', 'seq'})
    op = opt_enum(args, 'op', _OPS)
    if op == 'list':
        if 'seq' in args:
            raise ValueError("op 'list' does not take 'seq'")
        return {'op': 'list',
                'limit': opt_int(args, 'limit', lo=1, hi=200, default=20)}
    if 'limit' in args:
        raise ValueError("op 'undo' does not take 'limit'")
    if 'seq' in args:
        return {'op': 'undo', 'seq': req_seq(args)}
    return {'op': 'undo'}


def req_seq(args: Dict[str, Any]) -> int:
    seq = args['seq']
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        raise ValueError("field 'seq' must be a positive integer")
    return seq


async def _run_activity(args: Dict[str, Any], backend) -> Any:
    if args['op'] == 'list':
        entries = await offload(journal.entries, args['limit'])
        return {'count': len(entries), 'entries': entries}
    try:
        entry = await offload(journal.undo, args.get('seq'), backend)
    except journal.UndoError as e:
        raise ActionError('E_INTERNAL', str(e)[:200])
    return {'undone': {'seq': entry['seq'], 'kind': entry['kind'],
                       'summary': entry['summary']}}


register_action('activity', _run_activity, validate=_validate_activity,
                needs_lock=False, confirm=None,
                describe='Query/undo the F-3 journal of reversible state '
                         'changes (volume/brightness/window): list entries '
                         'or restore the previous state.')
