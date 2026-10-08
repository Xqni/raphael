"""Uniform per-stage latency timestamps (ARCH-6, CO-SHARE) — value-blind.

Stages (ms, last observed): stt, routing, llm_first_token, tool_start,
tts_first_audio. Anchors are per-rowid/per-job and pruned; a stage with no
anchor is OMITTED (honest — never a fabricated zero). Exposed via
GET /status -> `latency`.
"""
import time
from collections import deque
from typing import Any, Dict, Optional

STAGES = ('stt', 'routing', 'llm_first_token', 'tool_start', 'tts_first_audio')
_ANCHOR_CAP = 64

_last: Dict[str, float] = {}
_HIST_MAX = 120                     # AUD-29: bounded per-stage window
_hist: Dict[str, "deque[float]"] = {}
_anchors: Dict[int, Dict[str, float]] = {}     # rowid -> {submit, running}
_marks: Dict[int, Dict[str, bool]] = {}        # rowid -> once-flags
_job: Optional[str] = None                     # last running external id
_speak_anchor: Dict[str, float] = {}           # jid -> speak start (mono)
_updated_at: int = 0


def _now() -> float:
    return time.monotonic()


def _stamp(stage: str, ms: float) -> None:
    global _updated_at
    _last[stage] = max(0.0, float(ms))
    _updated_at = int(time.time() * 1000)
    h = _hist.get(stage)
    if h is None:
        h = _hist[stage] = deque(maxlen=_HIST_MAX)
    h.append(_last[stage])


def _pct(values, q: float) -> float:
    """Nearest-rank percentile on a small bounded list (value-blind numbers)."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    idx = max(0, min(len(ordered) - 1, int(round(q * (len(ordered) - 1)))))
    return round(ordered[idx], 1)


def _prune() -> None:
    while len(_anchors) > _ANCHOR_CAP:
        _anchors.pop(next(iter(_anchors)))
    while len(_marks) > _ANCHOR_CAP:
        _marks.pop(next(iter(_marks)))


def reset_for_tests() -> None:
    global _job, _updated_at
    _last.clear(); _anchors.clear(); _marks.clear(); _speak_anchor.clear()
    _hist.clear()
    _job = None; _updated_at = 0


# ---- anchors ---------------------------------------------------------------
def note_submit(rowid: int) -> None:
    _anchors.setdefault(int(rowid), {})['submit'] = _now()
    _prune()


def note_running(rowid: int, jid: str) -> None:
    global _job
    a = _anchors.setdefault(int(rowid), {})
    a['running'] = _now()
    _job = jid
    _prune()
    if 'submit' in a:
        _stamp('routing', (a['running'] - a['submit']) * 1000.0)


def _stage_since_running(rowid: int, stage: str) -> bool:
    """One-shot: record now-running for the stage (no anchor -> no number)."""
    a = _anchors.get(int(rowid)) or {}
    if 'running' not in a:
        return False
    flags = _marks.setdefault(int(rowid), {})
    if flags.get(stage):
        return False
    flags[stage] = True
    _stamp(stage, (_now() - a['running']) * 1000.0)
    return True


def note_llm_first_token(rowid: int) -> bool:
    return _stage_since_running(rowid, 'llm_first_token')


def note_tool_start(rowid: int) -> bool:
    return _stage_since_running(rowid, 'tool_start')


def note_stt(ms: float) -> None:
    _stamp('stt', ms)


def note_speak_start(jid: str) -> None:
    _speak_anchor[str(jid)] = _now()


def note_tts_first_audio(jid: str) -> None:
    t0 = _speak_anchor.pop(str(jid), None)
    if t0 is not None:
        _stamp('tts_first_audio', (_now() - t0) * 1000.0)


def snapshot() -> Dict[str, Any]:
    """Value-blind: stage names + numbers + job id only (no transcripts,
    no paths, no provider payloads)."""
    out: Dict[str, Any] = {'stages': {k: round(v, 1)
                                      for k, v in _last.items()}}
    # AUD-29: bounded histograms (p50/p95/max/count) — distributions, not a
    # single latest sample; value-blind (numbers only).
    hist = {}
    for stage, values in _hist.items():
        if values:
            hist[stage] = {'count': len(values),
                           'p50': _pct(values, 0.50),
                           'p95': _pct(values, 0.95),
                           'max': round(max(values), 1)}
    if hist:
        out['hist'] = hist
    if _job:
        out['job'] = _job
    if _updated_at:
        out['updated_at'] = _updated_at
    return out
