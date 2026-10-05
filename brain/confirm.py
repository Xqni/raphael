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
"""
import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Tools whose mere selection implies risk (tool registry metadata agrees).
RISKY_TOOLS = {
    'shell', 'powershell', 'exec', 'network', 'net', 'ssh', 'git_write',
    'files_delete', 'computer_use', 'browser',
}

# (pattern, human reason) — spoken question states action + target concisely.
RISKY_PATTERNS = [
    (re.compile(r'\b(shell|bash|powershell|cmd|exec|sudo|\brm\b|\bdel\b|format|kill|chmod|chown|reg\b|mkfs|dd\b)', re.I),
     'run a privileged/system command'),
    (re.compile(r'\b(delete|remove|erase|wipe|shred|drop\s+table|destroy|rmdir)\b', re.I),
     'delete files or data'),
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

DEFAULT_TIMEOUT_S = float(os.environ.get('RAPHAEL_CONFIRM_TIMEOUT_S', '30'))

YES_WORDS = {'yes', 'y', 'yeah', 'yep', 'yup', 'ok', 'okay', 'confirm', 'confirmed',
             'go', 'approve', 'approved', 'proceed', 'do it', 'sure', 'absolutely'}
NO_WORDS = {'no', 'n', 'nope', 'nah', 'abort', 'aborted', 'cancel', 'cancelled',
            'stop', 'deny', 'denied', 'never', 'no way', 'dont', "don't", 'do not'}


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


def classify(text: str, tool: Optional[str] = None) -> RiskDecision:
    """Decide whether a job needs user confirmation before dispatch."""
    hits: List[str] = []
    if tool and str(tool).lower() in RISKY_TOOLS:
        hits.append(f'tool `{tool}`')
    for pat, why in RISKY_PATTERNS:
        if pat.search(text or ''):
            hits.append(why)
    if not hits:
        return RiskDecision(needs=False)
    reason = hits[0]
    snippet = ' '.join((text or '').split())[:80]
    question = f"About to {reason}: “{snippet}”. Confirm?" if snippet else \
        f"About to {reason}. Confirm?"
    return RiskDecision(needs=True, question=question, actions=['yes', 'no'], reason=reason)


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
    """Per-job pending-confirmation registry. One future per job id."""

    def __init__(self, timeout_s: Optional[float] = None):
        self.timeout_s = float(timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S)
        self._pending: Dict[int, asyncio.Future] = {}

    def pending(self, job_id) -> bool:
        from .jobs import store
        rowid = store.parse_job_ref(job_id)
        return rowid in self._pending if rowid is not None else False

    def pending_ids(self) -> List[int]:
        return list(self._pending.keys())

    async def request(self, job_id, question: str, actions: List[str]) -> str:
        """Wait for an answer. Returns 'yes' | 'no' | 'timeout'. Never raises."""
        from .jobs import store
        rowid = store.parse_job_ref(job_id)
        if rowid is None:
            return 'no'
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rowid] = fut
        try:
            answer = await asyncio.wait_for(asyncio.shield(fut), timeout=self.timeout_s)
            return str(answer)
        except asyncio.TimeoutError:
            return 'timeout'
        except asyncio.CancelledError:
            self._pending.pop(rowid, None)
            raise
        finally:
            self._pending.pop(rowid, None)

    def resolve(self, job_id, answer: str) -> bool:
        from .jobs import store
        rowid = store.parse_job_ref(job_id)
        if rowid is None:
            return False
        fut = self._pending.get(rowid)
        if fut is None or fut.done():
            return False
        a = (answer or '').strip().lower()
        if a in ('yes', 'no') or a in YES_WORDS or a in NO_WORDS:
            fut.set_result('yes' if a in ('yes',) or a in YES_WORDS else 'no')
        else:
            fut.set_result(parse_free_text(answer))
        return True

    def cancel(self, job_id):
        from .jobs import store
        rowid = store.parse_job_ref(job_id)
        if rowid is None:
            return
        fut = self._pending.pop(rowid, None)
        if fut is not None and not fut.done():
            fut.cancel()
