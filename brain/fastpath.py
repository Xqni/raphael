"""Deterministic intent matcher (fast path) — runs BEFORE any LLM
(ARCHITECTURE §4). Open app/URL, YouTube search, volume/brightness, timers,
window ops, job status/cancel, mode toggles → instant dispatch, target <300 ms.

Handler signature: callable(text, ctx) -> IntentResult | None.
`register_intent(keyword, handler)` and `match_intent(command)` keep their
phase-1 signatures for external callers; `run_intent` is the loop entry.
"""
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
        if ' ' not in arg and '.' in arg:
            url = arg if '://' in arg else 'https://' + arg
            return IntentResult(text=f'Opening {arg}…',
                                tool='launch_url', tool_args={'url': url},
                                task_kind='web')
        return IntentResult(text=f'Opening {arg}…',
                            tool='open_app', tool_args={'name': arg},
                            task_kind='system')

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

    for _kw in ('what time', 'what is the time', "what's the time",
                'tell me the time', 'current time', 'what day is it',
                'what is the date', "what's the date", 'time today'):
        register_intent(_kw, _now)

    register_intent('open ', _open)
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
