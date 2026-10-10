"""pc tool group: window management (act_req: window, list_windows,
foreground_info)."""
from __future__ import annotations

from ._spec import ToolSpec, prop_enum, prop_int, prop_string, spec

_WINDOW_OPS = ['list', 'focus', 'minimize', 'maximize', 'restore', 'snap']
_ZONES = ['left', 'right', 'top', 'bottom', 'max']

SPECS = (
    spec(
        'window',
        'Manage windows on the PC: bring one to the foreground (focus), '
        'minimize, maximize, restore, tile it to a screen half (snap), or '
        'list all windows (op=list). Target a window with hwnd from '
        'list_windows (preferred) or its exact title. focus/snap/minimize/'
        'maximize/restore change the foreground, so they take the input '
        'lock.',
        {'op': prop_enum('Window operation.', _WINDOW_OPS),
         'hwnd': prop_int('Window handle from list_windows — required for '
                          'every op except list.', 1, 2147483647),
         'title': prop_string('Exact window title as an alternative target '
                              '(from list_windows).'),
         'zone': prop_enum('Screen zone — required when op=snap.', _ZONES)},
        ('op',),
        needs_lock=True,
        confirm='auto',
    ),
    spec(
        'list_windows',
        'List visible top-level windows on the PC (hwnd, title, process, '
        'pid, rect, foreground flag). Read-only — call this first to get the '
        'hwnd for window operations.',
        {},
        (),
        confirm='auto',
    ),
    spec(
        'foreground_info',
        'Describe the window currently in the foreground (title, process, '
        'pid). Read-only — used for privacy checks before screenshots: if '
        'the title/process matches privacy.blocklist_apps, the screenshot '
        'must not leave the machine.',
        {},
        (),
        confirm='auto',
    ),
)
