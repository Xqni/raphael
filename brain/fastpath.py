"""Deterministic intent matcher (fast path) — runs BEFORE any LLM
(ARCHITECTURE §4). Open app/URL, YouTube search, volume/brightness, timers,
window ops, job status/cancel, mode toggles → instant dispatch, target <300 ms.

Handler signature: callable(text, ctx) -> IntentResult | None.
`register_intent(keyword, handler)` and `match_intent(command)` keep their
phase-1 signatures for external callers; `run_intent` is the loop entry.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

_intents: Dict[str, Callable] = {}


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
            return IntentResult(text=f'Searching YouTube for {query}…',
                                tool='search_youtube',
                                tool_args={'query': query},
                                task_kind='web')
        if ' ' not in arg and '.' in arg:
            url = arg if '://' in arg else 'https://' + arg
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
        return IntentResult(text=f'Searching YouTube for {q}…',
                            tool='search_youtube', tool_args={'query': q},
                            task_kind='web')

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
                            task_kind='llm')

    def _simulation(text, ctx):
        # Wave-5 Simulation kind: routes to the agent loop WITH
        # kind=simulation -> tools OFF (no side effects ever possible).
        return IntentResult(text='', done=False, job_kind='simulation',
                            task_kind='llm')

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
    register_intent('echo ', _echo)
    register_intent('cancel all', _cancel_all)
    register_intent('stop everything', _cancel_all)
    register_intent('pause', _pause)
    register_intent('resume', _resume)
    register_intent('private on', _private_on)
    register_intent('private off', _private_off)
