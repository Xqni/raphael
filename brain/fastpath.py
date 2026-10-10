"""Deterministic intent matcher (fast path) — runs BEFORE any LLM
(ARCHITECTURE §4). Open app/URL, YouTube search, volume/brightness, timers,
window ops, job status/cancel, mode toggles → instant dispatch, target <300 ms.

Handler signature: callable(text, ctx) -> IntentResult | None.
`register_intent(keyword, handler)` and `match_intent(command)` keep their
phase-1 signatures for external callers; `run_intent` is the loop entry.

REUSE preference (Wave-5P UX pairing 2026-10-10, with pc-control P0): when
the freshly-pushed foreground window IS a browser, "open <site>" and
"search <q>" map to pc-control's `navigate_url` (foreground Ctrl+L+URL+Enter
through the input lock — the existing tab is reused). First-open — no
browser foreground, or navigate_url not yet registered — keeps
launch_url/search_youtube/open_app unchanged.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote_plus

_intents: Dict[str, Callable] = {}

# ---- browser-reuse detection (Wave-5P UX pairing, coord decision 2026-10-10)
# A repeat "open <site>"/"search <q>" must REUSE a running browser via
# pc-control's navigate-in-place (Ctrl+L through the input lock) instead of
# spawning a fresh window. First-open keeps launch_url/open_app.
# The foreground identity is "title | process" (ws foreground consumer);
# the process half is exact, the title half is suffix-matched ("… - Google
# Chrome"). Unknown/stale foreground = no reuse (launch — always safe).
_BROWSER_PROCESSES = ('chrome', 'msedge', 'firefox', 'brave', 'opera',
                      'vivaldi', 'chromium')
# full names are unambiguous as bare suffixes; short/ambiguous ones ("opera",
# "brave") only count after the title separator ("… - Opera"), so a media
# player showing "Grand Opera" can never fake a browser
_BROWSER_TITLE_SUFFIXES = ('google chrome', 'microsoft edge',
                           'mozilla firefox', 'chromium')
_BROWSER_TITLE_DASHED = ('brave', 'opera gx', 'opera', 'vivaldi', 'firefox')


def _browser_reuse_available() -> bool:
    """True when the freshly-pushed foreground window IS a browser tab."""
    try:
        from . import foreground
        ident = (foreground.provider() or '').lower()
    except Exception:  # noqa: BLE001 — fastpath never dies on cache state
        return False
    if not ident:
        return False
    if '|' in ident:
        proc = ident.rsplit('|', 1)[-1].strip()
        title = ident.split('|', 1)[0].strip()
        if any(proc.startswith(p) for p in _BROWSER_PROCESSES):
            return True
    else:
        title = ident
    if any(title.endswith(s) for s in _BROWSER_TITLE_SUFFIXES):
        return True
    return any(title.endswith(' - ' + s) or title.endswith(' — ' + s)
               for s in _BROWSER_TITLE_DASHED)


def _have_tool(name: str) -> bool:
    """Registry probe: the navigate tool is pc-control's half of the pairing
    — until it lands, the mapping safely falls back to launch_url."""
    try:
        from . import tools as tool_reg
        return name in tool_reg.names()
    except Exception:  # noqa: BLE001
        return False


def register_intent(keyword: str, handler: Callable):
    _intents[keyword.lower()] = handler


def match_intent(command: str):
    cmd = (command or '').strip().lower()
    for kw, handler in _intents.items():
        if cmd.startswith(kw):
            return handler
    return None


@dataclass
class IntentResult:
    text: str                        # narration shown/spoken to the user
    tool: Optional[str] = None       # tool-registry name to run after intent
    tool_args: Dict[str, Any] = field(default_factory=dict)
    needs_lock: bool = False         # execution touches mouse/keyboard/screen
    done: bool = True                # False → intent wants the LLM/router path
    task_kind: Optional[str] = None  # orb shape/task kind (INTERFACES §e):
    #                                  system|files|web|media|llm|gui|none
    job_kind: Optional[str] = None   # Wave-5 job kind (chat|analysis|
    #                                  simulation|act) — carried to the engine


@dataclass
class IntentCtx:
    engine: Any = None               # brain.jobs.engine.JobEngine
    mode: Any = None                 # brain.mode.ModeState


def run_intent(command: str, ctx: IntentCtx) -> Optional[IntentResult]:
    handler = match_intent(command)
    if handler is None:
        return None
    try:
        return handler(command, ctx)
    except TypeError:
        return handler(command)      # legacy single-arg handlers


def needs_lock_hint(text: str) -> bool:
    """Wave 5U P0.6 admission hint: True when this text's fastpath intent
    dispatches a tool whose registry meta needs the input lock. Mirrors the
    runtime condition (`lock_hint or meta.needs_lock`); handlers are
    deterministic and ctx-guarded, so probing with an empty ctx is pure.
    Fastpath miss / chat -> False (a chat job NEVER parks behind GUI work)."""
    res = run_intent(text, IntentCtx())
    if res is None or not res.tool:
        return False
    if getattr(res, 'needs_lock', False):
        return True
    try:
        from . import tools as tool_reg
        return bool(tool_reg.describe(res.tool).get('needs_lock'))
    except Exception:  # noqa: BLE001 — hint must never raise
        return False


def register_builtin_intents():
    """Built-in deterministic intents (no LLM). Wired by loop.py at import."""

    def _status(text, ctx):
        eng = getattr(ctx, 'engine', None)
        if eng is None:
            return None
        s = eng.stats()
        return IntentResult(
            text=(f"{s['jobs_active']} active, {s['jobs_queued']} queued, "
                  f"{s['jobs_pending_confirm']} awaiting confirmation."))

    def _echo(text, ctx):
        return IntentResult(text='Echo: ' + text[5:].strip())

    def _cancel_all(text, ctx):
        eng = getattr(ctx, 'engine', None)
        n = eng.cancel_all() if eng is not None else 0
        return IntentResult(text=f'Cancelled {n} job(s).')

    def _pause(text, ctx):
        if getattr(ctx, 'mode', None) is None:
            return None
        ctx.mode.set('pause')
        return IntentResult(text='Paused.')

    def _resume(text, ctx):
        if getattr(ctx, 'mode', None) is None:
            return None
        ctx.mode.set('resume')
        return IntentResult(text='Resumed.')

    def _private_on(text, ctx):
        if getattr(ctx, 'mode', None) is None:
            return None
        ctx.mode.set('private_on')
        return IntentResult(text='Private mode on.')

    def _private_off(text, ctx):
        if getattr(ctx, 'mode', None) is None:
            return None
        ctx.mode.set('private_off')
        return IntentResult(text='Private mode off.')

    def _open(text, ctx):
        arg = text[5:].strip()  # after 'open '
        if not arg:
            return None
        # Voice commands carry politeness tails ("open notepad please") — strip
        # trailing fillers so the app/site name stays clean (live gate 2026-10-07:
        # 'notepad please' failed app resolution on the acoustic E2E).
        _words = arg.split()
        _tail_fillers = {"please", "pls", "thanks", "now", "quickly"}
        while _words and _words[-1].lower().strip(".,!?") in _tail_fillers:
            _words.pop()
        arg = " ".join(_words)
        if not arg:
            return None
        # Wave-2 Bug B (router request APPROVED 2026-10-06): "open youtube and
        # search lo-fi" is a YOUTUBE SEARCH, not an app launch — open_app with
        # the whole phrase spawned a blank cmd window and failed live.
        m = re.match(r'^(?P<site>.+?)\s+and\s+search\s+(?P<query>.+)$', arg,
                     re.IGNORECASE)
        if m and 'youtube' in m.group('site').lower():
            query = m.group('query').strip()
            if _browser_reuse_available() and _have_tool('navigate_url'):
                return IntentResult(
                    text=f'Searching YouTube for {query}…',
                    tool='navigate_url',
                    tool_args={'url': 'https://www.youtube.com/results'
                                      '?search_query=' + quote_plus(query)},
                    task_kind='web')
            return IntentResult(text=f'Searching YouTube for {query}…',
                                tool='search_youtube',
                                tool_args={'query': query},
                                task_kind='web')
        if ' ' not in arg and '.' in arg:
            url = arg if '://' in arg else 'https://' + arg
            # UX pairing (coord decision 2026-10-10, with pc-control P0):
            # repeat open with a browser already up REUSES it —
            # navigate_url = foreground Ctrl+L+URL+Enter through the input
            # lock. First-open (no browser foreground, or the tool not yet
            # registered during the pairing window) keeps launch_url.
            if _browser_reuse_available() and _have_tool('navigate_url'):
                return IntentResult(text=f'Navigating to {arg}…',
                                    tool='navigate_url',
                                    tool_args={'url': url},
                                    task_kind='web')
            return IntentResult(text=f'Opening {arg}…',
                                tool='launch_url', tool_args={'url': url},
                                task_kind='web')
        return IntentResult(text=f'Opening {arg}…',
                            tool='open_app', tool_args={'name': arg},
                            task_kind='system')

    def _search(text, ctx):
        # NEW intent — the fastpath docstring already promised YouTube search
        q = re.sub(r'^(?:search(?:\s+for)?|youtube\s+search)\s+', '',
                   text.strip(), flags=re.IGNORECASE)
        q = re.sub(r'\s+on\s+youtube\.?$', '', q, flags=re.IGNORECASE).strip()
        if not q:
            return None
        # UX pairing (coord decision 2026-10-10): repeat search with a
        # browser up navigates the EXISTING tab to the results page.
        from . import worldstate as _ws_state
        _tab = _ws_state.active_tab()
        if _browser_reuse_available() and _have_tool('navigate_url'):
            _url = ('https://www.youtube.com/results?search_query='
                    + quote_plus(q))
            _ws_state.record_search(q, 'youtube', _url,
                                    tab_id=(_tab or {}).get('tab_id'))
            return IntentResult(
                text=f'Searching YouTube for {q}…',
                tool='navigate_url', tool_args={'url': _url},
                task_kind='web')
        _ws_state.record_search(q, 'youtube', '',
                                tab_id=(_tab or {}).get('tab_id'))
        return IntentResult(text=f'Searching YouTube for {q}…',
                            tool='search_youtube', tool_args={'query': q},
                            task_kind='web')

    def _confirm_policy_q(text, ctx):
        # P3: the policy map is config-owned; the answer is deterministic.
        from . import confirm as _confirm
        return IntentResult(text=_confirm.policy_summary(), task_kind='none')

    # ---- Wave 5U task 6: browser follow-ups (world-state seams) -----------
    # Tool names coordinated with pc-control (request brain-core__to__
    # pc-control__browser-followup-tools.md). Registry probe = safe pairing
    # window: tool not landed yet -> HONEST refusal, never fake success.
    def _no_browser_tool(name):
        return IntentResult(
            text=(f'The browser worker is not connected — I cannot do that '
                  f'yet ({name} unavailable).'),
            task_kind='none')

    def _scroll(text, ctx):
        direction = 'up' if 'up' in text else 'down'
        if _have_tool('browser_scroll'):
            return IntentResult(text=f'Scrolling {direction}.',
                                tool='browser_scroll',
                                tool_args={'direction': direction},
                                needs_lock=True, task_kind='gui')
        return _no_browser_tool('browser_scroll')

    def _go_back(text, ctx):
        if _have_tool('browser_back'):
            return IntentResult(text='Going back.', tool='browser_back',
                                tool_args={}, needs_lock=True,
                                task_kind='gui')
        return _no_browser_tool('browser_back')

    def _go_forward(text, ctx):
        if _have_tool('browser_forward'):
            return IntentResult(text='Going forward.', tool='browser_forward',
                                tool_args={}, needs_lock=True,
                                task_kind='gui')
        return _no_browser_tool('browser_forward')

    def _read_page(text, ctx):
        if _have_tool('browser_read'):
            return IntentResult(text='Reading the page.',
                                tool='browser_read', tool_args={},
                                task_kind='web')
        return _no_browser_tool('browser_read')

    def _open_result(text, ctx):
        m = re.search(
            r'\b(\d+|first|second|third|fourth|fifth|sixth|seventh|'
            r'eighth|ninth|tenth)\b', text, re.IGNORECASE)
        if not m:
            return None
        token = m.group(1).lower()
        _words = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4,
                  'fifth': 5, 'sixth': 6, 'seventh': 7, 'eighth': 8,
                  'ninth': 9, 'tenth': 10}
        n = _words.get(token) or (int(token) if token.isdigit() else 0)
        if not (1 <= n <= 10):
            return None
        if _have_tool('browser_click'):
            return IntentResult(text=f'Opening result {n}.',
                                tool='browser_click', tool_args={'n': n},
                                needs_lock=True, task_kind='gui')
        return _no_browser_tool('browser_click')

    # ---- Wave 5U task 7: background-task status intents -------------------
    def _task_status(text, ctx):
        eng = getattr(ctx, 'engine', None)
        if eng is None:
            return None
        return IntentResult(text=eng.task_status_text(), task_kind='none')

    def _working_on(text, ctx):
        eng = getattr(ctx, 'engine', None)
        if eng is None:
            return None
        st = eng.stats()
        head = f"{st['jobs_active']} active, {st['jobs_queued']} queued."
        task_line = eng.task_status_text()
        if task_line == 'No background tasks.':
            return IntentResult(text=head, task_kind='none')
        return IntentResult(text=f'{head} {task_line}', task_kind='none')

    def _cancel_task(text, ctx):
        eng = getattr(ctx, 'engine', None)
        if eng is None:
            return None
        substr = re.sub(r'^cancel the\s+', '', text.strip(), flags=re.I)
        substr = re.sub(r'\s+tasks?$', '', substr, flags=re.I).strip()
        job = eng.find_task(substr)
        if job is None:
            return IntentResult(text=f'No task matches “{substr[:40]}”.',
                                task_kind='none')
        eng.cancel(job['job'])
        return IntentResult(
            text=f'Cancelled “{(job.get("task") or "")[:60]}”.',
            task_kind='none')

    def _redirect_task(text, ctx):
        eng = getattr(ctx, 'engine', None)
        if eng is None:
            return None
        new_goal = re.sub(r'^(?:change|make) (?:it|the task) to\s+', '',
                          text.strip(), flags=re.I).strip()
        if not new_goal:
            return None
        job = eng.find_task('')
        if job is None:
            return IntentResult(text='No background task to change.',
                                task_kind='none')
        if eng.redirect_task(job['id'], new_goal) is None:
            return IntentResult(text='I could not switch that task.',
                                task_kind='none')
        return IntentResult(
            text=f'Switching the task to “{new_goal[:60]}”.',
            task_kind='none')

    def _screenshot(text, ctx):
        return IntentResult(text='Taking a screenshot…', tool='screenshot',
                            tool_args={'max_px': 1280}, task_kind='gui')

    def _now(text, ctx):
        from datetime import datetime
        now = datetime.now()
        h = now.hour % 12 or 12
        ampm = 'AM' if now.hour < 12 else 'PM'
        return IntentResult(
            text=(f"It's {h}:{now.minute:02d} {ampm} on {now:%A}, "
                  f"{now:%B} {now.day}, {now:%Y}"))

    def _see_screen(text, ctx):
        # computer-use hook (ACCEPTED 2026-10-06): Wave 2 exit criterion #3 —
        # the full utterance is the vision prompt (their service composes it).
        return IntentResult(text='Let me look.', tool='see_screen',
                            tool_args={'question': text}, needs_lock=False,
                            task_kind='gui')

    def _analysis(text, ctx):
        # Wave-5 Analysis kind: routes to the agent loop WITH kind=analysis
        # (read-only intent; tools stay available, confirm rules unchanged).
        return IntentResult(text='', done=False, job_kind='analysis',
                            task_kind='analysis')

    def _simulation(text, ctx):
        # Wave-5 Simulation kind: routes to the agent loop WITH
        # kind=simulation -> tools OFF (no side effects ever possible).
        return IntentResult(text='', done=False, job_kind='simulation',
                            task_kind='simulation')

    for _kw in ('analyze ', 'analysis of ', 'analyse '):
        register_intent(_kw, _analysis)
    for _kw in ('simulate ', 'simulation of ', 'simulate: '):
        register_intent(_kw, _simulation)

    for _kw in ('what am i looking at', "what's on my screen",
                'what is on my screen', 'describe my screen',
                'look at my screen', 'see my screen'):
        register_intent(_kw, _see_screen)

    for _kw in ('what time', 'what is the time', "what's the time",
                'tell me the time', 'current time', 'what day is it',
                'what is the date', "what's the date", 'time today'):
        register_intent(_kw, _now)

    # task 6 follow-ups — registered BEFORE 'open ' so result-ordinals win
    # the prefix race against the generic app/URL launch intent
    for _n, _w in ((1, 'first'), (2, 'second'), (3, 'third'), (4, 'fourth'),
                   (5, 'fifth'), (6, 'sixth'), (7, 'seventh'), (8, 'eighth'),
                   (9, 'ninth'), (10, 'tenth')):
        register_intent(f'open the {_w} result', _open_result)
        register_intent(f'open result {_n}', _open_result)
    register_intent('scroll down', _scroll)
    register_intent('scroll up', _scroll)
    for _kw in ('go back a page', 'go back', 'browser back'):
        register_intent(_kw, _go_back)
    for _kw in ('go forward a page', 'go forward', 'browser forward'):
        register_intent(_kw, _go_forward)
    for _kw in ('read this page', 'read the page'):
        register_intent(_kw, _read_page)
    register_intent('now search ', _search)
    register_intent('open ', _open)
    # Bug B (router request APPROVED): explicit search intents — the
    # docstring always promised YouTube search on the fast path.
    register_intent('search ', _search)
    register_intent('search for ', _search)
    register_intent('youtube ', _search)
    register_intent('screenshot', _screenshot)
    register_intent('take a screenshot', _screenshot)
    # NOTE: wake-extracted commands are punctuation-NORMALIZED — both forms
    # must exist or voice never matches (found: "what's running" kw vs the
    # transcript "whats running").
    register_intent("what's running", _status)
    register_intent('whats running', _status)
    register_intent('whats going on with my system', _status)
    register_intent('whats running', _status)
    register_intent('status', _status)
    # P3 spoken surface: "what requires your confirmation?" answers the
    # safety.confirm_policy map verbatim (deterministic, no LLM).
    register_intent('what requires your confirmation', _confirm_policy_q)
    register_intent('what requires confirmation', _confirm_policy_q)
    register_intent('what needs your confirmation', _confirm_policy_q)
    register_intent('what needs confirmation', _confirm_policy_q)
    register_intent('what do you need confirmation for', _confirm_policy_q)
    register_intent('what do you require confirmation for', _confirm_policy_q)
    # task 7 status intents ('cancel the ' after 'cancel all' — distinct
    # prefixes, insertion order preserved)
    for _kw in ("how's that task going", 'how is that task going',
                "what's that task doing", 'whats that task doing',
                'task status'):
        register_intent(_kw, _task_status)
    for _kw in ('what are you working on', 'what are you doing'):
        register_intent(_kw, _working_on)
    register_intent('cancel the ', _cancel_task)
    for _kw in ('change it to ', 'change the task to '):
        register_intent(_kw, _redirect_task)
    register_intent('echo ', _echo)
    register_intent('cancel all', _cancel_all)
    register_intent('stop everything', _cancel_all)
    register_intent('pause', _pause)
    register_intent('resume', _resume)
    register_intent('private on', _private_on)
    register_intent('private off', _private_off)
