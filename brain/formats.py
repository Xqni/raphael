"""Output-format emitters — Answer / Report (PROTOCOL §3 rows land with the
integrator at merge; APPROVED decision 2026-10-07 on
`brain-core__to__integrator__output-formats-and-job-kinds.md`).

Frames (roles **ui + cli only** — body keeps speak/subtitle as today;
INTERFACES §e untouched — these are NOT orb states):

  answer: {"type": "answer", "v": 1, "job", "text", "format": "answer",
           "provider"?, "model"?}
  report: {"type": "report", "v": 1, "job", "title", "summary",
           "sections": [{"heading", "text"}], "format": "report"}

Conditions from the decision (all enforced here, server-side BEFORE emit):
- `answer` is emitted for EVERY final reply (uniform — consumers dedupe by
  job). In Private Mode `provider`/`model` are omitted naturally: there is
  no router hop, so the emitter simply receives None and drops the keys.
- report caps: sections <= 10, summary <= 500 chars, per-section text <= 2000
  chars, trimmed BEFORE the frame goes on the wire.
- fail-silent: a dead hub can never fail a job.
"""
from typing import Any, Dict, List, Optional

ANSWER_FORMAT = 'answer'
REPORT_FORMAT = 'report'
REPORT_MAX_SECTIONS = 10
REPORT_SUMMARY_MAX = 500
REPORT_SECTION_MAX = 2000


def build_answer(job: Optional[str], text: str,
                 provider: Optional[str] = None,
                 model: Optional[str] = None) -> Dict[str, Any]:
    """The approved answer shape. provider/model only when the reply came
    through the router (Private Mode / fastpath replies omit them)."""
    frame: Dict[str, Any] = {'type': 'answer', 'v': 1,
                             'job': job, 'text': str(text),
                             'format': ANSWER_FORMAT}
    if provider:
        frame['provider'] = str(provider)
    if model:
        frame['model'] = str(model)
    return frame


def _sections_from(text: str) -> List[Dict[str, str]]:
    paragraphs = [p.strip() for p in str(text).split('\n\n') if p.strip()]
    if not paragraphs:
        paragraphs = [str(text).strip() or '']
    multi = len(paragraphs) > 1
    out: List[Dict[str, str]] = []
    for i, para in enumerate(paragraphs[:REPORT_MAX_SECTIONS]):
        heading = f'Part {i + 1}' if multi else 'Findings'
        out.append({'heading': heading,
                    'text': para[:REPORT_SECTION_MAX]})
    return out


def build_report(job: Optional[str], text: str,
                 title: Optional[str] = None) -> Dict[str, Any]:
    """The approved report shape — caps applied here, BEFORE emit."""
    body = str(text or '')
    return {
        'type': 'report', 'v': 1, 'job': job,
        'title': str(title or 'Report')[:200],
        'summary': body[:REPORT_SUMMARY_MAX],
        'sections': _sections_from(body),
        'format': REPORT_FORMAT,
    }


def _broadcast(hub, frame: Dict[str, Any]) -> bool:
    try:
        if hub is None:
            return False
        hub.broadcast(frame, roles={'ui', 'cli'})
        return True
    except Exception:  # noqa: BLE001 — a format emit can never fail a job
        return False


def answer(hub, job: Optional[str], text: str,
           provider: Optional[str] = None,
           model: Optional[str] = None) -> bool:
    """Emit the answer frame for ONE final reply (uniform rule)."""
    if hub is None or text is None:
        return False
    return _broadcast(hub, build_answer(job, text, provider, model))


def report(hub, job: Optional[str], text: str,
           title: Optional[str] = None) -> bool:
    """Emit the report frame (Analysis results / long-form)."""
    if hub is None or text is None:
        return False
    return _broadcast(hub, build_report(job, text, title))
