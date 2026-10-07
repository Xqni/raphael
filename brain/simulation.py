"""Simulation job type — Wave-5 sandboxed dry-run (evolution task-kind
contract [43] + qa privacy contract `analysis-simulation-privacy-contract`,
APPROVED 2026-10-07).

Semantics (assigned [43]):
- SANDBOXED dry-run: actions are PREDICTED and recorded as an act_req stream;
  they are NEVER dispatched — no body act_req, no local side-effect execution,
  no input lock, no second capture path (qa contract point 4);
- output = predicted act_req stream + Report (loop appends `predicted_lines()`
  to the Report text);
- native tools are OFF for simulation (formats contract [37] cond 4): the
  model plans from a hypothetical-action instruction (never a live catalog).

Privacy gates (qa contract points 1-3):
1. `gate(mode)` refuses under Private Mode — no model call happens;
2. `redact(text)` scrubs `privacy.redact` kinds before spoken/journaled/
   prompted/emitted output;
3. sandbox feedback handed BACK to the model is wrapped untrusted (AGENTS §9).
"""
import json
from typing import Any, Dict, List, Optional

from . import analysis as _analysis
from . import config as appcfg
from . import tools as tool_reg

NAME = 'simulation'


def gate(mode) -> Optional[str]:
    """Point 1 — Private Mode suppresses ALL Simulation model calls."""
    return _analysis.gate(mode)


def redact(text: Any) -> str:
    """Point 2 — shared deterministic scrubbing with Analysis."""
    return _analysis.redact(text)


class Sandbox:
    """In-process mock executor: records the predicted act_req stream and
    returns canned dry-run results. Touches nothing — no hub, no body, no
    local tool functions, no lock."""

    def __init__(self):
        self.predicted: List[Dict[str, Any]] = []

    def record(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        entry = {'action': tool, 'args': dict(args or {})}
        self.predicted.append(entry)
        return entry

    def run(self, tool: str, args: Dict[str, Any]) -> str:
        """Dry-run one planned action: record + return an UNSATISFIED-by-reality
        canned result (wrapped untrusted by the caller before the prompt)."""
        entry = self.record(tool, args)
        try:
            rendered = json.dumps(entry['args'], ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001 — never let rendering crash a job
            rendered = str(entry['args'])
        return (f'[SANDBOX dry-run] {entry["action"]}({rendered}) predicted; '
                f'nothing was executed.')

    def predicted_lines(self) -> List[str]:
        out = []
        for e in self.predicted:
            try:
                args = json.dumps(e['args'], ensure_ascii=False, default=str)
            except Exception:  # noqa: BLE001
                args = str(e['args'])
            out.append(f'{e["action"]} {args}')
        return out

    def report_suffix(self) -> str:
        """The predicted act_req stream, ready to append to the Report text
        (redaction applied by the caller)."""
        lines = self.predicted_lines()
        if not lines:
            return '\n\nPredicted actions: none.'
        return ('\n\nPredicted actions (dry-run, nothing executed):\n- '
                + '\n- '.join(lines))


def sandbox_feedback(tool: str, result: str) -> str:
    """Point 3 — dry-run feedback re-enters the prompt as untrusted data."""
    return tool_reg.as_untrusted(result, f'sandbox:{tool}')


def hypothetical_action_catalog() -> str:
    """The PLANNING vocabulary for a simulation (hypothetical-only — this is
    NOT the live tool catalog: native tools stay off, nothing here is
    callable; the loop only RECORDS predictions)."""
    specs = tool_reg.tool_specs()
    if not specs:
        return ''
    lines = ['SIMULATION DRY-RUN: you are not allowed to perform actions. '
             'If your plan would take actions, list each as one single-line '
             'JSON object {"tool": "<name>", "args": {...}} (hypothetical '
             'only — they will be recorded as predictions, never executed). '
             'Available hypothetical actions:']
    for s in specs:
        fn = (s or {}).get('function') or {}
        if fn.get('name'):
            lines.append(f'- {fn["name"]}: {fn.get("description", "")}')
    return '\n'.join(lines)
