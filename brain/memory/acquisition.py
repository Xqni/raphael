"""Predator-style skill acquisition — F-2 STUBS, DISABLED BY DEFAULT.

Design: docs/skills/ACQUISITION.md (read before touching this file).
Master switch: `skills.acquisition_enabled` — default FALSE in
config.d/tools-memory.yaml; a USER config edit enables it, never a model call
(same fail-closed pattern as plugins `enabled` and MCP `allow`).

Every public function returns {'enabled': False, ...} and performs ZERO side
effects while the flag is off. The module contains NO execution primitives
(no subprocess/shell imports): `test_draft` runs only a caller-INJECTED
runner; without one it reports 'skipped'. Promotion to published is a human
two-step on brain.memory.skills — this module deliberately has no publish.
"""
import re
from typing import Any, Callable, Dict, List, Optional

from . import skills as _skills

_DEFAULT_MIN_REPEATS = 3
_SECTION_HEAD = ('## When to Use', '## Procedure', '## Pitfalls',
                 '## Verification')

# in-memory observation counters (design-stage stub; see ACQUISITION.md
# "Future work" for journal persistence)
_observed: Dict[str, Dict[str, Any]] = {}


def _cfg(dotted: str, default):
    try:
        from .. import config as appcfg
        return appcfg.cfg_get(appcfg.get_config(), dotted, default)
    except Exception:  # noqa: BLE001
        return default


def enabled() -> bool:
    try:
        return bool(_cfg('skills.acquisition_enabled', False))
    except Exception:  # noqa: BLE001
        return False


def _signature(task: Any) -> str:
    """Normalized repeated-task signature: lowercase token set, sorted."""
    toks = sorted(set(re.findall(r'[a-z0-9]+', str(task or '').lower())))
    return ' '.join(toks[:24]) or '(empty)'


def _drafts_dir():
    return _skills.skills_dir() / '.drafts'


def _off() -> Dict[str, Any]:
    return {'enabled': False,
            'reason': 'skills.acquisition_enabled is false (user config gate)'}


def observe_failure(task: Any, *, error: Any = '') -> Dict[str, Any]:
    """Stage 1 — count a failed task. No-op while disabled."""
    if not enabled():
        return _off()
    sig = _signature(task)
    entry = _observed.setdefault(
        sig, {'count': 0, 'error': '', 'task': str(task or '')[:300]})
    entry['count'] += 1
    entry['error'] = str(error or entry['error'])[:500]
    try:
        threshold = int(_cfg('skills.acquisition_min_repeats',
                             _DEFAULT_MIN_REPEATS) or _DEFAULT_MIN_REPEATS)
    except Exception:  # noqa: BLE001
        threshold = _DEFAULT_MIN_REPEATS
    return {'enabled': True, 'signature': sig, 'count': entry['count'],
            'ready': entry['count'] >= threshold, 'threshold': threshold}


def _ready_count(task: Any) -> int:
    return int(_observed.get(_signature(task), {}).get('count', 0))


def maybe_draft(task: Any, *, error: Any = '', procedure: Any = '',
                verification: Any = '', name: Optional[str] = None,
                tags: tuple = ()) -> Dict[str, Any]:
    """Stage 2 — sandboxed draft (skills/.drafts/, always draft/below-gate).
    Only fires when the signature is READY; inherits create_skill's dedup and
    name validation. No-op while disabled."""
    if not enabled():
        return _off()
    if _ready_count(task) == 0:
        return {'enabled': True, 'status': 'not_ready',
                'reason': 'observe_failure never saw this signature'}
    title = str(task or '').strip()[:80] or 'acquired skill'
    skill_name = name or ('acq_' + re.sub(r'[^a-z0-9]+', '_',
                                          _signature(task))[:40].strip('_'))
    if not re.match(_skills.NAME_RE.pattern, skill_name):
        skill_name = 'acq_' + re.sub(r'[^a-z0-9]+', '_', skill_name)[:40].strip('_')
    body = (
        f'{_SECTION_HEAD[0]}\nWhen the repeated task "{title}" appears again.\n\n'
        f'{_SECTION_HEAD[1]}\n{str(procedure or "").strip() or "(to be filled from the failure evidence)"}\n\n'
        f'{_SECTION_HEAD[2]}\nError seen: {str(error or "").strip() or "(none recorded)"}\n\n'
        f'{_SECTION_HEAD[3]}\n{str(verification or "").strip() or "(define a verification step before publishing)"}\n'
    )
    try:
        created = _skills.create_skill(
            skill_name, f'acquired how-to: {title}', body,
            category='acquired', tags=tags, source='learned',
            confidence=0.0, status='draft', directory=_drafts_dir())
    except _skills.SkillError as e:
        return {'enabled': True, 'status': 'error', 'error': str(e)}
    return {'enabled': True, 'status': 'drafted', 'name': created,
            'sandbox': str(_drafts_dir() / created),
            'note': 'draft is below the confidence gate — never auto-injected'}


def test_draft(name: str, *, runner: Optional[Callable[[str], Any]] = None
               ) -> Dict[str, Any]:
    """Stage 3 — run the Verification section through an INJECTED runner.
    No runner -> 'skipped' (acquisition never executes anything itself)."""
    if not enabled():
        return _off()
    rec = _skills.get_skill(name, directory=_drafts_dir())
    if rec is None:
        return {'enabled': True, 'status': 'missing', 'name': name}
    verification = rec['body'].split('## Verification', 1)[-1].strip()
    if runner is None:
        return {'enabled': True, 'status': 'skipped', 'name': name,
                'reason': 'no test runner configured (never auto-executes)'}
    try:
        result = runner(verification)
        passed = bool(result) if isinstance(result, bool) else \
            (str(result).strip().lower() in ('ok', 'pass', 'passed', 'true'))
        return {'enabled': True, 'status': 'passed' if passed else 'failed',
                'name': name}
    except Exception as e:  # noqa: BLE001 — runner failure = test failure
        return {'enabled': True, 'status': 'failed', 'name': name,
                'error': f'{type(e).__name__}: {e}'}


def submit_for_approval(name: str) -> Dict[str, Any]:
    """Stage 4 — pin the draft BELOW the gate and ask the human. Promotion
    stays a human two-step (finalize + set_status/set_confidence); no publish
    here."""
    if not enabled():
        return _off()
    rec = _skills.get_skill(name, directory=_drafts_dir())
    if rec is None:
        return {'enabled': True, 'status': 'missing', 'name': name}
    # re-assert the safety posture before showing it to the user
    try:
        _skills.set_status(name, 'draft')
    except _skills.SkillError:
        pass
    return {
        'enabled': True, 'status': 'awaiting_approval', 'name': name,
        'prompt': (f'Sandbox draft {name!r} is ready (draft, confidence '
                   f'{rec.get("confidence", 0.0)} — below gate). Review '
                   f'git diff skills/.drafts/{name}/, then approve with '
                   f'finalize_draft({name!r}) followed by the human two-step '
                   f'set_status(published) + set_confidence(>= gate).'),
    }


def finalize_draft(name: str) -> Dict[str, Any]:
    """Stage 4b — HUMAN-approved move from the sandbox into the live
    `skills/` tree. Still draft + below-gate afterwards: moving does NOT
    activate the gate — only the human set_status/set_confidence two-step
    does. Disabled flag does NOT block this (it never activates anything)."""
    try:
        if not re.match(_skills.NAME_RE.pattern, str(name or '')):
            return {'enabled': enabled(), 'status': 'error',
                    'error': f'invalid name {name!r}'}
        src = _drafts_dir() / name
        dst = _skills.skills_dir() / name
        if not (src / 'SKILL.md').is_file():
            return {'enabled': enabled(), 'status': 'missing', 'name': name}
        if (dst / 'SKILL.md').exists():
            return {'enabled': enabled(), 'status': 'error',
                    'error': f'{name} already exists in the live tree'}
        dst.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.move(str(src), str(dst))
        # index keeps pointing at the moved path, counters intact
        _skills.sync()
        return {'enabled': enabled(), 'status': 'finalized', 'name': name,
                'path': str(dst), 'next': 'human two-step: set_status + '
                                          'set_confidence'}
    except Exception as e:  # noqa: BLE001
        return {'enabled': enabled(), 'status': 'error',
                'error': f'{type(e).__name__}: {e}'}


def list_drafts() -> List[Dict[str, Any]]:
    """Sandbox inventory for review (fail-silent). Independent of the flag —
    a human must always be able to SEE what exists, enabled or not."""
    out: List[Dict[str, Any]] = []
    try:
        d = _drafts_dir()
        if not d.is_dir():
            return out
        for p in sorted(d.glob('*/SKILL.md')):
            rec = _skills.get_skill(p.parent.name, directory=d)
            if rec:
                out.append({'name': rec['name'], 'status': rec['status'],
                            'confidence': rec['confidence'],
                            'path': str(p.parent)})
    except Exception:  # noqa: BLE001
        return out
    return out
