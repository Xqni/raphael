"""Per-tool failure-injection cases for the Wave-4 partial-failure matrix
(docs/lanes/pc-control.md, Wave 4: "act_res always truthful under crash").

Single source of truth shared by:
  * body/win/tests/test_pc_failure_matrix.py  (unit, FakeWin)
  * body/win/e2e_control.py                   (E2E injection phase)

Three tables, keyed by act_req action:
  INVALID_ARGS  — arguments that MUST fail validation with E_BAD_MSG,
                  BEFORE any OS call (side-effect-free refusal).
  CRASH_CASES   — {method, args}: the happy-path args plus the FakeWin
                  backend method that raises, so the dispatcher must answer
                  E_INTERNAL, release any lock, and stay usable.
Missing-required, wrong-value and denied-shape samples are mixed on purpose
("missing-denied" from the lane task).

Truthfulness contract asserted against these tables:
  ok:false  => zero side effects beyond the failing call itself;
  ok:true   => the side effect DID happen (happy matrix);
  after ANY failure the next dispatch succeeds (recovery).
"""

# action -> invalid args (all must be rejected pre-side-effect)
INVALID_ARGS = {
    'launch_url': {'url': 'javascript:alert(1)'},
    'search_youtube': {'query': ''},
    'open_app': {'name': ''},
    'open_path': {'path': '\\\\server\\share\\x.exe'},
    'powershell': {'script_id': 'rm-rf'},
    'screenshot': {'max_px': 99999},
    'uia': {'op': 'find', 'element': {}},
    'input': {'keys': []},
    'window': {'op': 'focus'},                  # missing target
    'list_windows': {'bogus': 1},
    'foreground_info': {'bogus': 1},
    'clipboard': {'op': 'read', 'text': 'x'},   # denied shape
    'media': {'op': 'eject'},
    'volume': {},                                # missing required
    'brightness': {'level': -1},
    'notify': {'text': ''},
    'list_running_apps': {'bogus': 1},
    'report': {'op': 'save', 'title': 't', 'body': 'not json', 'format': 'json'},
    'activity': {'op': 'teleport'},
    'navigate_url': {'url': 'javascript:alert(1)'},   # same scheme guard
}

# action -> (FakeWin method that raises BackendError, happy args)
CRASH_CASES = {
    'launch_url': ('open_url', {'url': 'https://example.com/crash'}),
    'search_youtube': ('open_url', {'query': 'crash'}),
    'open_app': ('path_commands', {'name': 'note'}),
    'open_path': ('open_shell', {'path': 'CRASH_PLACEHOLDER'}),  # filled per-run
    'powershell': ('powershell', {'script_id': 'sysinfo'}),
    'screenshot': ('capture', {}),
    'uia': ('uia_find', {'op': 'find', 'element': {'name': 'OK'}}),
    'input': ('type_text', {'text': 'x'}),
    'window': ('list_windows', {'op': 'list'}),
    'list_windows': ('list_windows', {}),
    'foreground_info': ('foreground', {}),
    'clipboard': ('clipboard_get', {'op': 'read'}),
    'media': ('media_key', {'op': 'play_pause'}),
    'volume': ('set_volume', {'level': 10}),
    'brightness': ('set_brightness', {'level': 10}),
    'notify': ('notify', {'text': 'crash'}),
    'list_running_apps': ('list_processes', {}),
    'report': ('reports_dir', {'op': 'save', 'title': 'Crash',
                               'body': 'crash body'}),
    'activity': ('set_volume', {'op': 'undo'}),
    'navigate_url': ('list_windows', {'url': 'https://crash.test'}),
}


def crash_args(action: str, tmp_path=None):
    """Args for the crash case (open_path needs a REAL existing path —
    existence is validated before the backend call; activity needs a
    JOURNALED entry so its undo path actually reaches the backend)."""
    method, args = CRASH_CASES[action]
    if action == 'open_path':
        target = (tmp_path / 'crash.txt') if tmp_path is not None else None
        if target is None:
            raise ValueError('open_path crash case needs tmp_path')
        if not target.exists():
            target.write_text('crash')
        return method, {'path': str(target)}
    if action == 'activity':
        from body.win import journal
        journal.record('volume', 'volume', 'crash-drill seed',
                       {'level': 40})
    return method, dict(args)
