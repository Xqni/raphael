"""pc tool group: launching + app discovery (act_req: launch_url,
search_youtube, open_app, open_path, list_running_apps)."""
from __future__ import annotations

from ._spec import ToolSpec, prop_string, spec

SPECS = (
    spec(
        'launch_url',
        'Open an absolute http(s) URL in the default browser on the Windows '
        'PC. Use for any website navigation. The URL must start with '
        'http:// or https:// (no javascript:/file:/data: URLs); spaces must '
        'be percent-encoded.',
        {'url': prop_string('Absolute http(s) URL to open, e.g. '
                            '"https://www.example.com/page".')},
        ('url',),
    ),
    spec(
        'search_youtube',
        'Open YouTube search results for a query on the Windows PC. Use '
        'instead of launch_url whenever the user wants to find/watch YouTube '
        'videos ("search X on YouTube", "play X").',
        {'query': prop_string('Search terms (max 200 chars), e.g. '
                              '"lo-fi hip hop".')},
        ('query',),
    ),
    spec(
        'open_app',
        'Launch an INSTALLED Windows application by name — curated sources '
        'only (Start Menu shortcuts, PATH executables, App Paths registry, '
        'UWP/Store apps). Use for "open <app>" commands. AUD-11 boundary: '
        'literal filesystem paths are NOT accepted here (use open_path, '
        'which is confirmation-gated) and names matching '
        'privacy.blocklist_apps (sensitive apps like password managers) are '
        'refused — launch those via open_path too. Check list_running_apps '
        'first if the app may already be running.',
        {'name': prop_string('Installed app name or executable stem, e.g. '
                             '"notepad", "chrome", "Calculator".')},
        ('name',),
    ),
    spec(
        'open_path',
        'Open an existing LOCAL file or folder with its Windows default '
        'handler (Explorer for folders). CONFIRMATION REQUIRED (AUD-11): '
        'handler-opening an arbitrary exe/document executes it — the gate '
        'asks before dispatch. Only real filesystem paths — no UNC/network '
        'paths, no shell: verbs. The path must already exist; folders are '
        'the safe case, executables/scripts run with their handler.',
        {'path': prop_string('Absolute local path, e.g. an existing file or '
                             'folder on this PC.')},
        ('path',),
        risky=True,
        confirm='open_arbitrary_file',
    ),
    spec(
        'list_running_apps',
        'List applications currently running on the Windows PC with their '
        'window titles. Read-only; use before window/app operations when you '
        'need to know what is open.',
        {},
        (),
    ),
)
