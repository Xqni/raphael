"""pc tool group: F-3 activity journal (act_req: activity).

Query the journal of reversible state changes and undo them (restore the
previous volume/brightness or window placement). Same data the orb viewer
renders via brain-core's relay.
"""
from __future__ import annotations

from ._spec import ToolSpec, prop_enum, prop_int, prop_string, spec

SPECS = (
    spec(
        'activity',
        'Inspect and undo Raphael\'s reversible PC changes (F-3 journal). '
        'op=list: newest-first reversible entries {seq, ts, id, kind, '
        'summary, undone}. op=log: the ORB activity view — every executed '
        'action with {id, ts, job, action, args, ok, error, summary, '
        'reversible, undo, undone, undo_ok} (read-only; reversible=false '
        'means no undo exists — never invent one). op=undo: restore the '
        'previous state of the newest undoable entry, or target one by seq '
        'or id (the id from op=log). Undo applies the inverse first and '
        'only then marks it undone; a failed undo reports an error, flips '
        'undo_ok=false and changes nothing. Use when the user asks "what '
        'did you change", "undo that", or "put it back".',
        {'op': prop_enum('list = reversible entries, log = full activity '
                         'view, undo = restore previous state.',
                         ['list', 'undo', 'log']),
         'limit': prop_int('Entries for op=list (1-200, default 20) / '
                           'op=log (1-200, default 30), newest first.', 1, 200),
         'seq': prop_int('Specific journal entry seq to undo (default: '
                         'newest undoable). Mutually exclusive with id.', 1,
                         2147483647),
         'id': prop_string('Stable entry id from op=log (starts with "a_") — '
                           'alternative undo target. Mutually exclusive with '
                           'seq.')},
        ('op',),
    ),
)
