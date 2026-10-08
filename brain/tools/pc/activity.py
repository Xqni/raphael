"""pc tool group: F-3 activity journal (act_req: activity).

Query the journal of reversible state changes and undo them (restore the
previous volume/brightness or window placement). Same data the orb viewer
renders via brain-core's relay.
"""
from __future__ import annotations

from ._spec import ToolSpec, prop_enum, prop_int, spec

SPECS = (
    spec(
        'activity',
        'Inspect and undo Raphael\'s reversible PC changes (F-3 journal): '
        'op=list returns newest-first entries {seq, ts, kind, summary, '
        'undone} for volume/brightness/window changes; op=undo restores the '
        'previous state of the newest undoable entry, or of a specific seq. '
        'Undo applies the inverse first and only then marks it undone — a '
        'failed undo reports an error and changes nothing. Use when the '
        'user asks "what did you change", "undo that", or "put it back".',
        {'op': prop_enum('list = journal entries, undo = restore previous '
                         'state.', ['list', 'undo']),
         'limit': prop_int('Entries to return for op=list (1-200, '
                           'default 20, newest first).', 1, 200),
         'seq': prop_int('Specific journal entry to undo (default: newest '
                         'undoable).', 1, 2147483647)},
        ('op',),
    ),
)
