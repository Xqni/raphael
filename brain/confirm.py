"""Confirmation enforcement — REAL (PROTOCOL §9, addendum §7).

Code-enforced, per-job, BEFORE tool dispatch. The phase-1 stub was always-true
— dangerous with the shell tool. Now:

- risky jobs (shell/exec/network/destructive/purchase/password/install/
  publish) emit `needs_confirm` to role=ui (and cli/body per §3) and the job
  sits in `awaiting_confirm`;
- the user answers via `confirm_resp` (speech STT, text, or orb menu);
- approve → the job continues and the scoped grant is journaled on the job;
- deny → job `cancelled`, spoken "Aborted.";
- timeout (default 30 s, RAPHAEL_CONFIRM_TIMEOUT_S) → abort, NEVER auto-approve;
- concurrent jobs each hold their own pending confirmation — confirming one
  never grants another (one future per job id).

HARDENING (Wave 2 task 3, 2026-10-06 — strengthens, never weakens §8):
- actions mapped to `config.yaml → safety.confirm_actions` are HIGH risk;
- HIGH risk requires a NON-voice confirmation (orb click or typed): a voice
  "yes" is REJECTED (`rejected_channel`) because open-mic speech can be
  injected by anything playing in the room; a voice "no"/deny always works
  (denying is always safe);
- LOW risk (not on the config list) still accepts voice yes;
- timeout still aborts, never auto-approves.
"""
import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Tools whose mere selection implies risk (tool registry metadata agrees).
RISKY_TOOLS = {
    'shell', 'powershell', 'exec', 'network', 'net', 'ssh', 'git_write',
    'files_delete', 'computer_use', 'browser',
}

# (pattern, human reason) — spoken question states action + target concisely.
# ORDER = specificity: deletions before generic privileged commands so an
# `rm`/`del` reads as "delete files or data" (HIGH per config list), not as a
# generic system command.
RISKY_PATTERNS = [
    (re.compile(r'\b(delete|remove|erase|wipe|shred|drop\s+table|destroy|rmdir|rm|del|unlink)\b', re.I),
     'delete files or data'),
    (re.compile(r'\b(shell|bash|powershell|cmd|exec|sudo|format|kill|chmod|chown|reg\b|mkfs|dd\b)', re.I),
     'run a privileged/system command'),
    (re.compile(r'\b(purchase|buy|order|checkout|subscribe|pay|transfer\s+money)\b', re.I),
     'make a purchase or move money'),
    (re.compile(r'\b(install|uninstall|upgrade)\b[^\n]{0,40}\b(package|app|software|driver|update)', re.I),
     'install or uninstall software'),
    (re.compile(r'\b(password|credential|secret|private\s+key|api\s+key|token)\b', re.I),
     'handle credentials'),
    (re.compile(r'\b(public repo|make public|push|publish|tweet|post|send message|send email|share)\b', re.I),
     'publish or send something externally'),
    (re.compile(r'\b(system settings?|registry|boot\s+order|firewall|sudoers)\b', re.I),
     'change system settings'),
    (re.compile(r'\b(ssh|sftp|scp|curl|wget|ftp|http[s]?://)\b', re.I),
     'use the network'),
]

# reason -> normalized action id (ids match config safety.confirm_actions so
# "high risk = the config list" is a set intersection, not a vibe check).
ACTION_BY_REASON = {
    'delete files or data': 'delete_files',
    'make a purchase or move money': 'purchase',
    'install or uninstall software': 'install_software',
    'handle credentials': 'enter_password',
    'change system settings': 'system_settings_change',
    'run a privileged/system command': 'system_command',
    'publish or send something externally': 'send_message',
    'use the network': 'network',
}
# tool registry name -> action id (RISKY_TOOLS entry absent => tool's own name)
TOOL_ACTION = {
    'files_delete': 'delete_files',
    'shell': 'system_command',
    'powershell': 'system_command',
    'exec': 'system_command',
    'ssh': 'network',
    'git_write': 'git_write',
    'computer_use': 'computer_use',
    'network': 'network',
    'net': 'network',
    'browser': 'network',
}

DEFAULT_TIMEOUT_S = float(os.environ.get('RAPHAEL_CONFIRM_TIMEOUT_S', '30'))

YES_WORDS = {'yes', 'y', 'yeah', 'yep', 'yup', 'ok', 'okay', 'confirm', 'confirmed',
             'go', 'approve', 'approved', 'proceed', 'do it', 'sure', 'absolutely'}
NO_WORDS = {'no', 'n', 'nope', 'nah', 'abort', 'aborted', 'cancel', 'cancelled',
            'stop', 'deny', 'denied', 'never', 'no way', 'dont', "don't", 'do not'}

# voice channel values (where an answer came from)
CHANNEL_VOICE = 'voice'      # STT / open mic — injectable
CHANNEL_CLICK = 'click'      # orb menu/click
CHANNEL_TEXT = 'text'        # typed (CLI or UI text entry)


class Denied(Exception):
    """User answered no."""


class ConfirmTimeout(Exception):
    """No answer within the deadline — abort, never auto-approve."""


@dataclass
class RiskDecision:
    needs: bool
    question: str = ''
    actions: List[str] = field(default_factory=list)
    reason: str = ''
    action: str = ''          # normalized action id (config-list style)
    risk: str = 'low'         # 'high' -> NON-voice confirmation required


def high_risk_actions() -> set:
    """The config authority for HIGH risk (Wave 2 task 3)."""
    try:
        from brain import config as _cfg
        actions = _cfg.cfg_get(_cfg.get_config(), 'safety.confirm_actions', []) or []
        return {str(a) for a in actions}
    except Exception:  # noqa: BLE001 — config unavailable -> conservative default
        return {'delete_files', 'send_message', 'send_email', 'purchase',
                'enter_password', 'system_settings_change', 'install_software',
                'make_public_repo'}


def classify(text: str, tool: Optional[str] = None) -> RiskDecision:
    """Decide whether a job needs user confirmation before dispatch.

    All hits are collected; risk is HIGH when ANY hit maps onto
    `config.safety.confirm_actions` (the question prefers the high hit)."""
    hits: List[Tuple[str, str]] = []       # (action id, human reason)
    if tool and str(tool).lower() in RISKY_TOOLS:
        tname = str(tool).lower()
        hits.append((TOOL_ACTION.get(tname, tname), f'tool `{tool}`'))
    for pat, why in RISKY_PATTERNS:
        if pat.search(text or ''):
            hits.append((ACTION_BY_REASON.get(why, 'other'), why))
    if not hits:
        return RiskDecision(needs=False)
    high = high_risk_actions()
    is_high = any(action in high for action, _ in hits)
    action, reason = next(((a, r) for a, r in hits if a in high), hits[0])
    # AUD-09 (P0): a TOOL-sourced decision (dispatch-time `tool=` argument)
    # defaults to NON-voice approval — mapped actions like system_command/
    # git_write/network/computer_use/plugin names are NOT in the config list,
    # and an open-mic "yes" must not authorize them. Explicit reviewed policy
    # arrives via registry meta confirm='voice_ok' (loop layer).
    if tool:
        is_high = True
    snippet = ' '.join((text or '').split())[:80]
    question = f"About to {reason}: “{snippet}”. Confirm?" if snippet else \
        f"About to {reason}. Confirm?"
    return RiskDecision(needs=True, question=question, actions=['yes', 'no'],
                        reason=reason, action=action,
                        risk='high' if is_high else 'low')


def voice_safe(job_id) -> bool:
    """Voice-answer risk predicate (voice request piece 1, assigned
    2026-10-06): True ONLY when a confirmation is pending for `job_id` and
    its risk is exactly 'low'.

    Risk unknown / pending gone / high → False. Callers must treat False as
    high-risk (refuse voice answers) — the low/high split is Core Guard
    semantics (AGENT_RULES §8) and is never re-derived by the voice lane.
    Backed by the RiskDecision recorded when `needs_confirm` was emitted."""
    from .jobs import store as job_store
    from .jobs.engine import get_engine
    rowid = job_store.parse_job_ref(job_id)
    if rowid is None:
        return False
    confirmer = get_engine().confirmer
    if rowid not in confirmer.pending_ids():
        return False
    return confirmer.risk_for(rowid) == 'low'


def tool_decision(tool: str, text: str = '') -> RiskDecision:
    """Dispatch-time gate for a tool whose REGISTRY metadata says `risky`
    (pc-control item 3) even when its name is not in RISKY_TOOLS and the
    user's text matched no pattern — e.g. a namespace registering a risky
    action under a new name.

    AUD-09 (P0): ALWAYS non-voice (`risk='high'`) — risky/unknown tools
    default to non-voice approval unless the registry carries the explicit
    reviewed policy confirm='voice_ok' (loop layer may downgrade)."""
    name = str(tool or '').strip()
    action = TOOL_ACTION.get(name.lower(), name.lower() or 'tool')
    risk = 'high'
    snippet = ' '.join((text or '').split())[:80]
    question = (f"About to run tool `{name}`: “{snippet}”. Confirm?"
                if snippet else f"About to run tool `{name}`. Confirm?")
    return RiskDecision(needs=True, question=question, actions=['yes', 'no'],
                        reason=f'tool `{name}` (risky metadata)',
                        action=action, risk=risk)


def parse_free_text(answer: str) -> str:
    """§9: free text goes through a small yes/no/modify intent check.
    Anything not clearly affirmative FAILS CLOSED (treated as deny)."""
    a = (answer or '').strip().lower().strip('.,!?')
    words = a.split()
    first = words[0] if words else ''
    if a in YES_WORDS or first in YES_WORDS:
        return 'yes'
    if a in NO_WORDS or first in NO_WORDS:
        return 'no'
    return 'no'  # modify/unclear -> abort; user re-issues the command


class Confirmer:
    """Per-job pending-confirmation registry. One future per job id.

    HARDENING: each pending request carries its risk (`high`/`low`); answers
    carry their channel (`voice`/`click`/`text`). A voice AFFIRMATIVE on a
    high-risk confirmation is rejected — the future stays pending so the user
    can still confirm from the orb or keyboard (or let it time out = abort).
    """

    def __init__(self, timeout_s: Optional[float] = None):
        self.timeout_s = float(timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S)
        self._pending: Dict[int, asyncio.Future] = {}
        self._risk: Dict[int, str] = {}

    def pending(self, job_id) -> bool:
        from .jobs import store
        rowid = store.parse_job_ref(job_id)
        return rowid in self._pending if rowid is not None else False

    def pending_ids(self) -> List[int]:
        return list(self._pending.keys())

    def risk_for(self, job_id) -> Optional[str]:
        from .jobs import store
        rowid = store.parse_job_ref(job_id)
        return self._risk.get(rowid)

    async def request(self, job_id, question: str, actions: List[str],
                      risk: str = 'low') -> str:
        """Wait for an answer. Returns 'yes' | 'no' | 'timeout'. Never raises."""
        from .jobs import store
        rowid = store.parse_job_ref(job_id)
        if rowid is None:
            return 'no'
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rowid] = fut
        self._risk[rowid] = 'high' if risk == 'high' else 'low'
        try:
            answer = await asyncio.wait_for(asyncio.shield(fut), timeout=self.timeout_s)
            return str(answer)
        except asyncio.TimeoutError:
            return 'timeout'
        except asyncio.CancelledError:
            self._pending.pop(rowid, None)
            self._risk.pop(rowid, None)
            raise
        finally:
            self._pending.pop(rowid, None)
            self._risk.pop(rowid, None)

    def resolve_ex(self, job_id, answer: str, via: str = CHANNEL_TEXT) -> str:
        """Returns 'ok' (future resolved) | 'rejected_channel' (voice yes on a
        high-risk confirmation — pending stays) | 'none' (nothing pending)."""
        from .jobs import store
        rowid = store.parse_job_ref(job_id)
        if rowid is None:
            return 'none'
        fut = self._pending.get(rowid)
        if fut is None or fut.done():
            return 'none'
        a = (answer or '').strip().lower()
        is_yes = a == 'yes' or a in YES_WORDS
        is_no = a == 'no' or a in NO_WORDS
        if not (is_yes or is_no):
            parsed = parse_free_text(answer)
            is_yes, is_no = parsed == 'yes', parsed == 'no'
        # HARDENING: high-risk x voice x affirmative -> reject, keep pending
        if via == CHANNEL_VOICE and is_yes and self._risk.get(rowid) == 'high':
            return 'rejected_channel'
        fut.set_result('yes' if is_yes else 'no')
        return 'ok'

    def resolve(self, job_id, answer: str, via: str = CHANNEL_TEXT) -> bool:
        """Back-compat bool wrapper (True = the future was resolved)."""
        return self.resolve_ex(job_id, answer, via=via) == 'ok'

    def resolve_oldest_pending(self, answer: str, via: str) -> Tuple[str, Optional[int]]:
        """Free-text/voice answer for the OLDEST pending confirmation.
        Returns (result, rowid) — result per resolve_ex()."""
        if not self._pending:
            return ('none', None)
        rowid = min(self._pending)
        return (self.resolve_ex(rowid, answer, via=via), rowid)

    def cancel(self, job_id):
        from .jobs import store
        rowid = store.parse_job_ref(job_id)
        if rowid is None:
            return
        fut = self._pending.pop(rowid, None)
        self._risk.pop(rowid, None)
        if fut is not None and not fut.done():
            fut.cancel()
