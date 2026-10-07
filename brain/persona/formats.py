"""Answer / Notice / Report reply formats (Wave 5; design 02 §3).

Shaping only — the loop produces the content, this module decides the SHAPE:
which format applies, what may be spoken (≤ voice_personality caps), and what
goes to screen. No new frame is needed: the spoken text rides `speak`, the
screen text rides `subtitle`, and proactive items ride the integrator-approved
`notice` frame (docs/PROTOCOL.md §3) — formats never invent carriers.

Classifier is DETERMINISTIC (event kind first); anything unrecognized degrades
to Answer — misclassification must never fabricate a proactive Notice
(design 02 §3).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Report-class job kinds: only these turn a terminal job_event into a Report.
# (Analysis/Simulation values follow the integrator request for the task_kind
# enum — accepted values are included so formatting works the moment it lands.)
REPORT_JOB_KINDS = frozenset({
    "analysis", "simulation", "report", "digest", "weekly_summary",
})

_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def truncate_sentences(text: str, max_sentences: int) -> str:
    """First N sentences, re-joined. N<=0 or short text returns as-is (never
    raises — shaping must not break a reply)."""
    if not text or max_sentences <= 0:
        return text or ""
    parts = [p for p in _SENTENCE.split(text.strip()) if p]
    if not parts:
        return text.strip()
    return " ".join(parts[:max_sentences])


def _caps(cfg: Dict[str, Any]) -> Dict[str, int]:
    vp = cfg.get("voice_personality") or {}
    answer_cap = int(vp.get("spoken_reply_max_sentences", 2))
    # design 02 §3: a Notice is ONE sentence + its actionable item
    notice_cap = int(vp.get("notice_max_sentences", 1))
    return {"answer": max(answer_cap, 1), "notice": max(notice_cap, 1),
            "report": max(answer_cap, 1)}


def pick_format(event: Dict[str, Any]) -> str:
    """Deterministic format selection from the event the loop already has.

    event: {"kind": "question"|"proactive"|"job_done"|"other",
            "task_kind"?: str, "job_class"?: str}
    Unknown kinds / missing fields => "answer" (fail-safe degradation)."""
    kind = (event or {}).get("kind")
    if kind == "proactive":
        return "notice"
    if kind == "job_done":
        cls = event.get("task_kind") or event.get("job_class") or ""
        return "report" if cls in REPORT_JOB_KINDS else "answer"
    return "answer"          # question, other, unknown, empty


def shape_reply(text: str, fmt: str, cfg: Dict[str, Any],
                private: bool = False) -> Dict[str, Any]:
    """Apply a format. Returns {format, spoken, screen}.

    - spoken respects the per-format sentence cap (voice_personality caps);
    - screen carries the FULL detail (design 02 §3: long detail on screen);
    - private mode suppresses the screen/subtitle (PROTOCOL §8/§9 invariant)
      while speech stays shaped the same way.
    Unknown fmt degrades to answer. Never raises."""
    caps = _caps(cfg)
    if fmt not in caps:
        fmt = "answer"
    cap = caps[fmt]
    spoken = truncate_sentences(text, cap)
    screen: Optional[str] = None if private else (text or "")
    return {"format": fmt, "spoken": spoken, "screen": screen}


def format_event(text: str, event: Dict[str, Any], cfg: Dict[str, Any],
                 private: bool = False) -> Dict[str, Any]:
    """pick + shape in one call (the loop's common path)."""
    return shape_reply(text, pick_format(event), cfg, private=private)
