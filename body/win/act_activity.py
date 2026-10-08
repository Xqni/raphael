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
    from actions import (offload, ActionError, opt_enum, opt_int, reject_extra,
                         register_action)

_OPS = {'list', 'undo', 'log'}


def _validate_activity(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'op', 'limit', 'seq', 'id'})
    op = opt_enum(args, 'op', _OPS)
    if op in ('list', 'log'):
        if 'seq' in args or 'id' in args:
            raise ValueError("op '%s' does not take seq/id" % op)
        return {'op': op,
                'limit': opt_int(args, 'limit', lo=1, hi=200,
                                 default=20 if op == 'list' else 30)}
    # undo: optional seq XOR optional id (orb gives ids, brain/LLM may use seq)
    if 'limit' in args:
        raise ValueError("op 'undo' does not take 'limit'")
    out = {'op': 'undo'}
    if 'seq' in args and 'id' in args:
        raise ValueError("pass either seq or id for undo, not both")
    if 'seq' in args:
        out['seq'] = req_seq(args)
    if 'id' in args:
        entry_id = args['id']
        if not isinstance(entry_id, str) or not entry_id.startswith('a_') \
                or len(entry_id) > 48:
            raise ValueError("field 'id' must be a journal entry id")
        out['id'] = entry_id
    return out


def req_seq(args: Dict[str, Any]) -> int:
    seq = args['seq']
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        raise ValueError("field 'seq' must be a positive integer")
    return seq


async def _run_activity(args: Dict[str, Any], backend) -> Any:
    if args['op'] == 'list':
        entries = await offload(journal.entries, args['limit'])
        return {'count': len(entries), 'entries': entries}
    if args['op'] == 'log':
        # orb-viewer contract: ALL executed acts joined with reversibility
        entries = await offload(journal.log_entries, args['limit'])
        return {'count': len(entries), 'entries': entries}
    try:
        entry = await offload(journal.undo, args.get('seq'), backend,
                              entry_id=args.get('id'))
    except journal.UndoError as e:
        raise ActionError('E_INTERNAL', str(e)[:200])
    return {'undone': {'seq': entry['seq'], 'kind': entry['kind'],
                       'summary': entry['summary'],
                       **({'id': entry['id']} if entry.get('id') else {})}}


register_action('activity', _run_activity, validate=_validate_activity,
                needs_lock=False, confirm=None,
                describe='Query/undo the F-3 journal of reversible state '
                         'changes (volume/brightness/window): list entries '
                         'or restore the previous state.')
