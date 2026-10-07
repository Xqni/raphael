"""act_req dispatcher for the Windows Body (PROTOCOL §7).

Responsibilities, in order:

1. allow-list — only actions in the §7 enum (plus the three additions
   requested in docs/requests/pc-control__to__integrator__protocol-act-req-enum.md)
   ever reach a handler; anything else answers `E_UNSUPPORTED`;
2. strict arg validation — every handler validates its own args (extra keys
   rejected, ranges enforced, no value ever echoed back in error text);
3. input-lock etiquette — `lock:true` from the Brain OR a handler flagged
   `needs_lock` requires the Body input lock; a busy lock fails fast with
   `act_res{ok:false, error:"E_LOCK_BUSY", queued:true}` (§7) — the Brain
   queues at job level, Body is last-line enforcement;
4. timeout — `timeout_ms` (default 30 s) except `atomic` actions, which run
   as ONE uninterruptible unit so a chord/mouse sequence can never be left
   half-executed (§5 cancellation rule);
5. action log — every dispatch is appended to logs/actions[_<instance>].log
   as JSONL with a redacted args summary and a STRUCTURAL result summary
   (screen/clipboard contents never touch disk, §7).

Handlers live in the act_* group modules and talk to the OS exclusively via
the winlayer backend — unit tests bind a fake backend and never inject real
input (AGENT_RULES §5).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

try:
    from . import automation, instance, winlayer
except ImportError:  # script mode (python body/win/ws_client.py)
    import automation
    import instance
    import winlayer

# ---------------------------------------------------------------------------
LOCK_WAIT_S = 0.1             # fast-fail window before E_LOCK_BUSY (§7)
DEFAULT_TIMEOUT_MS = 30000    # loop.py sends 30000; tolerate absent/None
MAX_TIMEOUT_MS = 120000       # hard cap even if the sender asks for more
LOG_MAX_BYTES = 5 * 1024 * 1024  # rotate the action log (1 backup)

# Actions pending addition to the PROTOCOL §7 enum — tracked in
# docs/requests/pc-control__to__integrator__protocol-act-req-enum.md so the
# conformance test can assert registry == §7 enum + these three.
PENDING_PROTO_ADDITIONS = ('list_windows', 'foreground_info', 'list_running_apps')


class ActionError(Exception):
    """Handler failure with a PROTOCOL §10 code. NEVER echoes arg values
    (the message ends up in the action log and the job error)."""

    def __init__(self, code: str, message: str):
        super().__init__('%s: %s' % (code, message))
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Action:
    name: str
    handler: Callable[[Dict[str, Any], Any], Awaitable[Any]]
    validate: Callable[[Dict[str, Any]], Dict[str, Any]]
    needs_lock: bool
    confirm: Optional[str]   # confirm category (INTERFACES §b metadata)
    describe: str
    atomic: bool             # run as one uninterruptible unit (no timeout cut)


ACTIONS: Dict[str, Action] = {}
_GROUPS = ('act_launch', 'act_powershell', 'act_capture', 'act_uia',
           'act_input', 'act_window', 'act_system')
_groups_loaded = False


def register_action(name: str, handler, *, validate, needs_lock: bool = False,
                    confirm: Optional[str] = None, describe: str = '',
                    atomic: bool = False) -> None:
    """Called by the act_* group modules at import time."""
    if name in ACTIONS:
        raise ValueError('duplicate act_req action: %s' % name)
    if not describe:
        raise ValueError('action %s needs a description' % name)
    ACTIONS[name] = Action(name=name, handler=handler, validate=validate,
                           needs_lock=needs_lock, confirm=confirm,
                           describe=describe, atomic=atomic)


def _import_group(name: str) -> None:
    import importlib
    if __package__:
        importlib.import_module('.' + name, __package__)
    else:
        importlib.import_module(name)


def load_groups() -> None:
    """Import the act_* modules once (idempotent, safe before dispatch)."""
    global _groups_loaded
    if _groups_loaded:
        return
    _groups_loaded = True   # set first: group modules call register_action
    for group in _GROUPS:
        _import_group(group)


def action_names():
    load_groups()
    return sorted(ACTIONS)


def get_action(name: str) -> Optional[Action]:
    load_groups()
    return ACTIONS.get(name)


# ---------------------------------------------------------------- args ----
# Shared validation helpers. Messages name the FIELD, never the VALUE.

def reject_extra(args: Dict[str, Any], allowed: set, where: str = 'args') -> None:
    extra = sorted(set(args) - allowed)
    if extra:
        raise ValueError('%s has unknown field(s): %s' % (where, ', '.join(extra)))


def req_str(args: Dict[str, Any], key: str, *, max_len: int,
            min_len: int = 1, default: Optional[str] = None,
            allow_empty: bool = False) -> str:
    if key not in args:
        if default is not None:
            return default
        raise ValueError("missing required field '%s'" % key)
    v = args[key]
    if not isinstance(v, str):
        raise ValueError("field '%s' must be a string" % key)
    if not allow_empty and not v.strip() and min_len:
        raise ValueError("field '%s' must not be empty" % key)
    if len(v) > max_len:
        raise ValueError("field '%s' exceeds %d characters" % (key, max_len))
    if any(ord(ch) < 32 and ch not in '\n\r\t' for ch in v):
        raise ValueError("field '%s' contains control characters" % key)
    return v


def opt_str(args: Dict[str, Any], key: str, *, max_len: int,
            default: Optional[str] = None) -> Optional[str]:
    if key not in args or args[key] is None:
        return default
    return req_str(args, key, max_len=max_len)


def req_int(args: Dict[str, Any], key: str, *, lo: int, hi: int,
            default: Optional[int] = None) -> int:
    if key not in args:
        if default is not None:
            return default
        raise ValueError("missing required field '%s'" % key)
    v = args[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError("field '%s' must be an integer" % key)
    if not (lo <= v <= hi):
        raise ValueError("field '%s' must be between %d and %d" % (key, lo, hi))
    return v


def opt_int(args: Dict[str, Any], key: str, *, lo: int, hi: int,
            default: int) -> int:
    if key not in args or args[key] is None:
        return default
    return req_int(args, key, lo=lo, hi=hi)


def opt_bool(args: Dict[str, Any], key: str, *, default: bool = False) -> bool:
    if key not in args or args[key] is None:
        return default
    v = args[key]
    if not isinstance(v, bool):
        raise ValueError("field '%s' must be a boolean" % key)
    return v


def opt_enum(args: Dict[str, Any], key: str, choices, default=None):
    if key not in args or args[key] is None:
        if default is not None:
            return default
        raise ValueError("missing required field '%s'" % key)
    v = args[key]
    if not isinstance(v, str) or v not in choices:
        raise ValueError("field '%s' must be one of: %s"
                         % (key, ', '.join(sorted(choices))))
    return v


# ------------------------------------------------------------ redaction ----
_REDACT_KEY_RE = re.compile(
    r'(api[_-]?key|token|password|passwd|secret|credential|card|cvv|ssn|'
    r'private[_-]?key|auth)', re.I)
_REDACT_WORD_RE = re.compile(
    r'\b(api[_-]?key|token|password|passwd|secret|credential|card|cvv)\b', re.I)
# Actions whose 'text' field carries user/clipboard/screen CONTENT: length only.
_CONTENT_ACTIONS = {'clipboard', 'uia', 'input'}
_MAX_STR = 120


def _clean(s: str, limit: int = _MAX_STR) -> str:
    s = ''.join(ch if 32 <= ord(ch) < 127 else ' ' for ch in s)
    return s if len(s) <= limit else s[:limit] + '...[+%d]' % (len(s) - limit)


def summarize_args(action: str, args: Any, _depth: int = 0) -> Any:
    """Args summary for the action log — secrets redacted, long values
    truncated, content-bearing text reduced to its length."""
    if _depth > 3:
        return '[deep]'
    if isinstance(args, dict):
        out = {}
        for k, v in args.items():
            if _REDACT_KEY_RE.search(str(k)):
                out[k] = '***'
            elif str(k) == 'text' and action in _CONTENT_ACTIONS:
                out[k] = '[len=%d]' % len(v) if isinstance(v, str) else '***'
            else:
                out[k] = summarize_args(action, v, _depth + 1)
        return out
    if isinstance(args, list):
        items = [summarize_args(action, v, _depth + 1) for v in args[:16]]
        if len(args) > 16:
            items.append('[+%d more]' % (len(args) - 16))
        return items
    if isinstance(args, str):
        if _REDACT_WORD_RE.search(args):
            return '***[redacted]'
        return _clean(args)
    if isinstance(args, (int, float, bool)) or args is None:
        return args
    return '[%s]' % type(args).__name__


def summarize_result(res: Dict[str, Any]) -> Any:
    """STRUCTURAL result summary only — strings become their length, so
    screen/clipboard content never reaches the log (§7: no secrets)."""
    if not res.get('ok'):
        err = str(res.get('error') or '')
        return {'ok': False, 'error': err[:200]}
    return {'ok': True, 'result': _brief(res.get('result'), 0)}


def _brief(v: Any, depth: int) -> Any:
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return '[chars=%d]' % len(v)
    if isinstance(v, dict):
        if depth >= 2:
            return '[dict]'
        return {k: _brief(x, depth + 1) for k, x in list(v.items())[:24]}
    if isinstance(v, list):
        return '[list:%d]' % len(v)
    return '[%s]' % type(v).__name__


def _log(job, action: str, args: Any, res: Dict[str, Any], t0: float,
         held: bool) -> None:
    """PROTOCOL §7 action log. Best-effort: logging never breaks a dispatch."""
    try:
        path = instance.action_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(path)
        err = res.get('error')
        line = {
            'ts': int(time.time() * 1000),
            'instance': instance.instance_name(),
            'job': job,
            'action': action,
            'ok': bool(res.get('ok')),
            'error': (str(err)[:200] if err else None),
            'ms': int((time.monotonic() - t0) * 1000),
            'lock': bool(held),
            'args': summarize_args(action, args),
            'result': summarize_result(res),
        }
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + '\n')
    except Exception as e:  # noqa: BLE001 — log is never load-bearing
        print('[actions] action-log write failed: %s' % e, flush=True)


def _rotate_if_needed(path) -> None:
    try:
        if path.is_file() and path.stat().st_size > LOG_MAX_BYTES:
            backup = path.with_suffix(path.suffix + '.1')
            backup.unlink(missing_ok=True)
            path.replace(backup)
    except OSError:
        pass


def _timeout_s(timeout_ms: Any) -> float:
    try:
        ms = int(timeout_ms)
    except (TypeError, ValueError):
        ms = DEFAULT_TIMEOUT_MS
    if ms <= 0:
        ms = DEFAULT_TIMEOUT_MS
    return min(ms, MAX_TIMEOUT_MS) / 1000.0


# ------------------------------------------------------------ dispatch ----
async def dispatch(action: str, args: Any, *, lock: bool = False,
                   job: Any = None, timeout_ms: Any = None,
                   backend: Any = None) -> Dict[str, Any]:
    """Execute one act_req. Returns the act_res payload (ok/result/error[/queued])."""
    load_groups()
    t0 = time.monotonic()
    held = False
    spec = ACTIONS.get(action)

    if spec is None:
        res = {"ok": False,
               "error": "E_UNSUPPORTED: unknown action '%s'" % str(action)[:80]}
        _log(job, str(action)[:80], args if isinstance(args, dict) else {}, res, t0, False)
        return res

    if not isinstance(args, dict):
        res = {"ok": False, "error": "E_BAD_MSG: args must be a JSON object"}
        _log(job, action, {}, res, t0, False)
        return res

    try:
        norm = spec.validate(dict(args))
    except (ValueError, TypeError, KeyError) as e:
        res = {"ok": False, "error": "E_BAD_MSG: %s" % (str(e)[:200] or 'invalid args')}
        _log(job, action, args, res, t0, False)
        return res

    # Input-lock etiquette: the sender's `lock` flag OR the action's own
    # needs_lock metadata (defense in depth — Body never injects input
    # without holding the lock, even if the Brain forgot to ask for it).
    if lock or spec.needs_lock:
        held = await automation.acquire_input_lock(LOCK_WAIT_S)
        if not held:
            # PROTOCOL §7: fail fast; Brain queues at job level.
            return {"ok": False, "error": "E_LOCK_BUSY", "queued": True}

    try:
        be = backend if backend is not None else winlayer.get_backend()
        try:
            if spec.atomic:
                # ONE uninterruptible unit: no wait_for, so a chord/mouse
                # sequence can never be cut in half (PROTOCOL §5).
                out = await spec.handler(norm, be)
            else:
                out = await asyncio.wait_for(spec.handler(norm, be),
                                             timeout=_timeout_s(timeout_ms))
        except ActionError as e:
            res = {"ok": False, "error": "%s: %s" % (e.code, e.message)}
        except asyncio.TimeoutError:
            res = {"ok": False,
                   "error": "E_TIMEOUT: action exceeded %.0fs"
                            % _timeout_s(timeout_ms)}
        except winlayer.BackendError as e:
            res = {"ok": False, "error": "E_INTERNAL: %s" % str(e)[:200]}
        except (ValueError, TypeError) as e:
            res = {"ok": False, "error": "E_BAD_MSG: %s" % (str(e)[:200] or 'invalid args')}
        except Exception as e:  # noqa: BLE001 — one action must never kill the body
            res = {"ok": False,
                   "error": "E_INTERNAL: %s: %s" % (type(e).__name__, str(e)[:180])}
        else:
            res = {"ok": True, "result": out}
    finally:
        if held:
            automation.release_input_lock()

    _log(job, action, norm, res, t0, held)
    return res
