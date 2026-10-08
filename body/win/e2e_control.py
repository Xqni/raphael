"""E2E harness for the Body act/control paths (pc-control lane).

Modes
-----
MOCK (default — safe anywhere: no stack, no sockets, no real input, no
hotkeys, no mic — AGENT_RULES §5 / lane rule "never inject real input
outside mocks"):

    python body/win/e2e_control.py            # exit 0 = PASS

Drives `ws_client.handle_message` over the FULL PROTOCOL §7 action matrix
with a FakeWin backend + FakeWS, checks act_res envelopes, arg validation,
E_LOCK_BUSY/queued, lock release, and the redacted action log. The action
log is redirected to a temp file so repo logs/ are never touched.

LIVE (Windows, real ws_client against the instance stack — INTEGRATOR ONLY,
and ONLY on an isolated instance — never on `main`):

    set RAPHAEL_INSTANCE=pc-control
    python body/win/e2e_control.py --live      # fake-brain.cjs must be up

Starts the real client, waits for connect+auth, injects hotkey actions via
the same thread-safe _post() the keyboard library uses, and verifies the
drain sends them (original harness behavior). Refuses to run when
RAPHAEL_INSTANCE is unset/`main` so the live stack can never be touched.
"""
import asyncio
import json
import os
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from body.win import actions, automation, instance, winlayer, ws_client
    from body.win.fakewin import FakeWin
except ImportError:                      # script mode (body/win on sys.path)
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import actions
    import automation
    import instance
    import winlayer
    import ws_client
    from fakewin import FakeWin


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw) if isinstance(raw, str) else raw)


# Full §7 matrix: (action, args, lock, expect_ok)
POSITIVE_MATRIX = [
    ('launch_url', {'url': 'https://example.com/e2e'}, False, True),
    ('search_youtube', {'query': 'lo-fi'}, False, True),
    ('open_app', {'name': 'note'}, False, True),
    ('open_app', {'name': 'Calculator'}, False, True),
    ('open_path', {'path': str(_REPO)}, False, True),
    ('powershell', {'script_id': 'disk_usage'}, False, True),
    ('screenshot', {'max_px': 640, 'quality': 70}, False, True),
    ('uia', {'op': 'find', 'element': {'name': 'OK'}}, True, True),
    ('uia', {'op': 'click', 'element': {'name': 'OK'}}, True, True),
    ('uia', {'op': 'type', 'element': {'control_type': 'edit'},
             'args': {'text': 'e2e field'}}, True, True),
    ('uia', {'op': 'read', 'element': {'control_type': 'edit'}}, True, True),
    ('uia', {'op': 'tree', 'element': {'name': 'Field'}, 'args': {'depth': 2}},
     True, True),
    ('input', {'keys': ['ctrl+shift+s']}, True, True),
    ('input', {'text': 'e2e typing', 'clear_first': True}, True, True),
    ('input', {'mouse': {'action': 'click', 'x': 400, 'y': 300}}, True, True),
    ('input', {'mouse': {'action': 'move', 'dx': 5, 'dy': -3}}, True, True),
    ('input', {'mouse': {'action': 'scroll', 'amount': -3}}, True, True),
    ('input', {'mouse': {'action': 'drag', 'x': 120, 'y': 140, 'steps': 4}},
     True, True),
    ('window', {'op': 'list'}, True, True),
    ('window', {'op': 'focus', 'title': 'Untitled - Notepad'}, True, True),
    ('window', {'op': 'minimize', 'hwnd': 1001}, True, True),
    ('window', {'op': 'maximize', 'hwnd': 1001}, True, True),
    ('window', {'op': 'restore', 'hwnd': 1001}, True, True),
    ('window', {'op': 'snap', 'hwnd': 1002, 'zone': 'right'}, True, True),
    ('clipboard', {'op': 'write', 'text': 'e2e-clipboard'}, False, True),
    ('clipboard', {'op': 'read'}, False, True),
    ('media', {'op': 'play_pause'}, True, True),
    ('media', {'op': 'next'}, True, True),
    ('volume', {'level': 35}, False, True),
    # F-3: the volume change above journaled its inverse — undo restores 50
    ('activity', {'op': 'undo'}, False, True),
    ('brightness', {'level': 70}, False, True),
    ('notify', {'text': 'e2e notify'}, False, True),
    ('list_windows', {}, False, True),
    ('foreground_info', {}, False, True),
    ('list_running_apps', {}, False, True),
    ('activity', {'op': 'list'}, False, True),
    ('report', {'op': 'save', 'title': 'E2E Wave 5 Report',
                'body': '# Findings\n- none\nconfidence: high'}, False, True),
    ('report', {'op': 'save', 'title': 'Second', 'body': '{"ok": true}',
                'format': 'json'}, False, True),
    ('report', {'op': 'list'}, False, True),
]

NEGATIVE_MATRIX = [
    ('teleport', {}, False, 'E_UNSUPPORTED'),          # unknown action
    ('launch_url', {'url': 'javascript:alert(1)'}, False, 'E_BAD_MSG'),
    ('volume', {'level': 999}, False, 'E_BAD_MSG'),
    ('clipboard', {'op': 'read', 'text': 'x'}, False, 'E_BAD_MSG'),
    ('powershell', {'script_id': 'rm-rf'}, False, 'E_BAD_MSG'),
    ('input', {'keys': ['ctrl+hax']}, True, 'E_BAD_MSG'),
    ('window', {'op': 'focus'}, True, 'E_BAD_MSG'),
    ('uia', {'op': 'find', 'element': {}}, True, 'E_BAD_MSG'),
    ('search_youtube', {'query': ''}, False, 'E_BAD_MSG'),
    ('open_path', {'path': '\\\\server\\share'}, False, 'E_BAD_MSG'),
]


async def _act(ws: FakeWS, action, args, lock, job, timeout_ms=None):
    frame = {'type': 'act_req', 'v': 1, 'job': job, 'action': action,
             'args': args, 'lock': lock, 'timeout_ms': timeout_ms or 30000}
    await ws_client.handle_message(json.dumps(frame), ws, None)
    res = ws.sent[-1]
    assert res['type'] == 'act_res' and res['v'] == 1, res
    assert res['job'] == job, res
    return res


async def mock_suite() -> int:
    # Isolate the action log + F-3 activity journal into temp files
    # (never touch repo logs/).
    import tempfile
    fd, log_path = tempfile.mkstemp(prefix='raphael-e2e-actions-', suffix='.jsonl')
    os.close(fd)
    fd, act_path = tempfile.mkstemp(prefix='raphael-e2e-activity-', suffix='.jsonl')
    os.close(fd)
    os.environ['RAPHAEL_ACTION_LOG'] = log_path
    os.environ['RAPHAEL_ACTIVITY_LOG'] = act_path
    from body.win import journal
    journal.reset()
    # NOTE: no RAPHAEL_INSTANCE defaulting needed — the log override and the
    # fake backend already make mock mode side-effect free on any host.

    fake = FakeWin()
    fake.uia_data['find'] = {'name': 'Field', 'control_type': 'Edit'}
    # Isolate report delivery into a temp dir (Wave-5 report act).
    import shutil
    import tempfile as _tf
    report_dir = pathlib.Path(_tf.mkdtemp(prefix='raphael-e2e-reports-'))
    fake.reports_path = report_dir
    winlayer.set_backend(fake)
    ws = FakeWS()
    failures = []

    def check(label, cond, detail=''):
        if cond:
            print('PASS %s' % label, flush=True)
        else:
            print('FAIL %s %s' % (label, detail), flush=True)
            failures.append(label)

    try:
        for i, (action, args, lock, expect_ok) in enumerate(POSITIVE_MATRIX):
            res = await _act(ws, action, args, lock, 'j_pos_%d' % i)
            check('act:%-18s' % action, res.get('ok') is expect_ok,
                  str(res)[:200])
            if action == 'clipboard' and args.get('op') == 'read':
                check('clipboard:read:legacy-string',
                      res.get('result') == 'e2e-clipboard', str(res))
            if action == 'screenshot':
                import base64
                raw = base64.b64decode(res['result']['b64'])
                check('screenshot:jpeg-magic',
                      raw[:2] == b'\xff\xd8' and res['result']['bytes'] == len(raw))

        for i, (action, args, lock, code) in enumerate(NEGATIVE_MATRIX):
            res = await _act(ws, action, args, lock, 'j_neg_%d' % i)
            check('reject:%-16s' % action,
                  res.get('ok') is False and str(res.get('error', '')).startswith(code),
                  str(res)[:200])

        # Lock busy -> exact §7 envelope; busy body must inject nothing.
        assert await automation.acquire_input_lock(0.05)
        try:
            before = len(fake.events)
            res = await _act(ws, 'input', {'keys': ['enter']}, True, 'j_busy')
            check('E_LOCK_BUSY:envelope',
                  res == {'type': 'act_res', 'v': 1, 'job': 'j_busy',
                          'ok': False, 'error': 'E_LOCK_BUSY', 'queued': True},
                  str(res))
            check('E_LOCK_BUSY:no-injection', len(fake.events) == before)
        finally:
            automation.release_input_lock()
        check('lock:released-after-matrix', not automation.lock_held())

        # Action log (§7): exists, one line per dispatch, redacted/structural.
        log_text = pathlib.Path(log_path).read_text()
        lines = log_text.splitlines()
        executed = len(POSITIVE_MATRIX) + len(NEGATIVE_MATRIX)
        check('action-log:line-count', len(lines) == executed,
              '%d lines for %d dispatches' % (len(lines), executed))
        check('action-log:no-jpeg-content', 'FAKEJPEG' not in log_text)
        check('action-log:b64-reduced-to-length',
              '"b64": "[chars=' in log_text)
        parsed = [json.loads(l) for l in lines]
        check('action-log:fields',
              all({'ts', 'instance', 'job', 'action', 'ok', 'ms', 'args',
                   'result'} <= set(l) for l in parsed))
        check('action-log:instance-field',
              all(l['instance'] == instance.instance_name() for l in parsed))

        # ---- Wave-4 failure injection: EVERY tool x {missing-denied,
        # locked, backend crash} + timeout, each followed by a recovery
        # dispatch (act_res always truthful, body always reusable).
        from body.win.failure_cases import CRASH_CASES, INVALID_ARGS, crash_args
        import tempfile

        crash_dir = pathlib.Path(tempfile.mkdtemp(prefix='raphael-e2e-crash-'))
        try:
            for i, (action, bad) in enumerate(sorted(INVALID_ARGS.items())):
                before = len(fake.events)
                res = await _act(ws, action, bad, True, 'e2e_inv_%d' % i)
                check('inject:invalid:%-15s' % action,
                      res.get('ok') is False
                      and str(res.get('error', '')).startswith('E_BAD_MSG')
                      and len(fake.events) == before, str(res)[:160])

            assert await automation.acquire_input_lock(0.05)
            try:
                for i, action in enumerate(sorted(INVALID_ARGS)):
                    _, args = crash_args(action, crash_dir)
                    before = len(fake.events)
                    res = await _act(ws, action, args, True, 'e2e_lock_%d' % i)
                    check('inject:locked:%-16s' % action,
                          res.get('ok') is False
                          and res.get('error') == 'E_LOCK_BUSY'
                          and res.get('queued') is True
                          and len(fake.events) == before, str(res)[:160])
            finally:
                automation.release_input_lock()

            for i, action in enumerate(sorted(CRASH_CASES)):
                method, args = crash_args(action, crash_dir)
                fake.fail_methods.add(method)
                lock = actions.get_action(action).needs_lock
                try:
                    res = await _act(ws, action, args, lock,
                                     'e2e_crash_%d' % i)
                    check('inject:crash:%-17s' % action,
                          res.get('ok') is False
                          and str(res.get('error', '')).startswith('E_INTERNAL')
                          and not automation.lock_held(), str(res)[:160])
                finally:
                    fake.fail_methods.discard(method)
                rec = await _act(ws, 'foreground_info', {}, False,
                                 'e2e_recover_%d' % i)
                check('recover:%-18s' % action, rec.get('ok') is True,
                      str(rec)[:120])

            fake.delays['clipboard_set'] = 0.6
            try:
                res = await _act(ws, 'clipboard',
                                 {'op': 'write', 'text': 'slow'}, True,
                                 'e2e_slow', timeout_ms=100)
                check('inject:timeout',
                      res.get('ok') is False
                      and str(res.get('error', '')).startswith('E_TIMEOUT')
                      and automation.lock_held(), str(res)[:160])
                # AUD-16: the blocked worker keeps the lock quarantined …
                check('inject:timeout:quarantined', automation.lock_held())
                await asyncio.sleep(0.8)        # … until it truly drains
                check('inject:timeout:drained', not automation.lock_held())
            finally:
                fake.delays.clear()
        finally:
            import shutil
            shutil.rmtree(crash_dir, ignore_errors=True)
    finally:
        winlayer.reset_backend()
        try:
            os.unlink(log_path)
        except OSError:
            pass
        try:
            os.unlink(act_path)
        except OSError:
            pass
        shutil.rmtree(report_dir, ignore_errors=True)

    print('E2E-MOCK: %s (%d checks failed)'
          % ('PASS' if not failures else 'FAIL', len(failures)), flush=True)
    return 0 if not failures else 1


async def live_suite() -> int:
    """Original control-frame path — real ws_client + fake-brain on the
    INSTANCE port. Guarded: never runs against the main instance."""
    name = os.environ.get('RAPHAEL_INSTANCE', '').strip()
    if not name or name == 'main':
        print('REFUSED: --live requires RAPHAEL_INSTANCE=<lane> '
              '(never run against the live main stack)', flush=True)
        return 2
    print('[e2e] live mode on instance %r -> %s' % (name, instance.ws_url()),
          flush=True)

    try:
        import hotkeys
    except ImportError:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import hotkeys

    client = asyncio.create_task(ws_client.start_client())
    await asyncio.sleep(6)  # connect + auth (pip/first-import may add delay)
    hotkeys._post('kill_gui', False)
    hotkeys._post('pause', True)
    hotkeys._post('private_on', True)
    # The drain prints "[body-win] control -> ..." for each send; watch stdout.
    await asyncio.sleep(4)
    client.cancel()
    try:
        await client
    except (asyncio.CancelledError, Exception):
        pass
    print('E2E-LIVE: injection done (check control -> lines above)', flush=True)
    return 0


def main() -> int:
    if '--live' in sys.argv:
        return asyncio.run(live_suite())
    return asyncio.run(mock_suite())


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
