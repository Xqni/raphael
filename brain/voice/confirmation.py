"""brain/voice/confirmation.py — yes/no/modify parsing for VOICE confirmations
(Wave 2 task 4; PROTOCOL §9.2 "free text goes through a small intent check
(yes/no/modify)", REQUIREMENTS_ADDENDUM §7).

Scope and safety (the part that matters):
  * LOW-risk confirmations only. `to_confirm_answer(..., low_risk=False)`
    ALWAYS returns None — a voice "yes" can never resolve a high-risk
    confirmation; those are answered through the non-voice channels
    (orb menu / typed confirm_resp) which brain-core owns. The low/high split
    itself lives in brain/confirm.py (Core Guard, AGENT_RULES §8) — this
    module never reclassifies risk, it only asks the caller to pass it in.
  * FAIL CLOSED: unclear speech resolves to "no answer" (None), never to
    "yes". Timeout on the caller's side still aborts (confirm.py), so an
    unrecognized mumble can never approve an action.

Vocabulary is seeded from brain/confirm.py's YES_WORDS/NO_WORDS (lazy import,
read-only) so spoken and typed answers classify identically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Set

from .wake import normalize_text

# ---- vocabularies ----------------------------------------------------------
_FALLBACK_YES = {"yes", "y", "yeah", "yep", "yup", "ya", "ok", "okay", "okey",
                 "confirm", "confirmed", "go", "approve", "approved", "proceed",
                 "do it", "sure", "absolutely", "affirmative", "correct",
                 "right", "mhm", "mm hm", "uh huh", "uhhum", "yep sure"}
_FALLBACK_NO = {"no", "n", "nope", "nah", "nuh uh", "abort", "aborted",
                "cancel", "cancelled", "stop", "deny", "denied", "never",
                "no way", "dont", "don't", "do not", "negative", "negative"}

# Words that turn a bare yes/no into a CONDITIONAL (addendum §7: "yes, but
# only the PDFs") -> the caller must re-ask, not proceed.
_MODIFY_MARKERS = (" but ", " instead", " actually", " wait", " change ",
                   " make it", "not quite", " except ", " only ", " rather ",
                   " can you ", " could you ", " hold on", " different ")


def _confirm_words(kind: str, fallback: Set[str]) -> Set[str]:
    """Read-only view of brain/confirm.py's vocab (kept in sync lazily); if
    the Core Guard module is unavailable we still classify correctly."""
    try:
        from .. import confirm as confirm_mod  # brain.confirm (not edited here)
        shared = getattr(confirm_mod, "YES_WORDS" if kind == "yes"
                         else "NO_WORDS", None)
        if isinstance(shared, set) and shared:
            return set(shared) | fallback
    except Exception:  # noqa: BLE001 — voice parsing must never fail to import
        pass
    return set(fallback)


@dataclass
class VoiceAnswer:
    """kind: 'yes' | 'no' | 'modify' | 'unrecognized'."""
    kind: str
    detail: str = ""
    raw: str = ""

    @property
    def definitive(self) -> bool:
        """True when the speech alone states a decision (yes/no)."""
        return self.kind in ("yes", "no")

    def __bool__(self) -> bool:
        return self.kind != "unrecognized"


def parse_voice_answer(text: str) -> VoiceAnswer:
    """Transcript -> VoiceAnswer. Never raises; '' -> unrecognized.

    Rules (order matters):
      - "yes, but <anything>"        -> modify (conditional, addendum §7)
      - bare/first-word yes          -> yes
      - bare/first-word no           -> no
      - modify markers anywhere      -> modify
      - anything else                -> unrecognized (fail closed)
    """
    raw = (text or "").strip()
    norm = normalize_text(raw)
    if not norm:
        return VoiceAnswer("unrecognized", detail="", raw=raw)
    words = norm.split()
    first = " ".join(words[:2])          # "uh huh" / "no way" count as first
    tail = f" {norm} "
    yes_words = _confirm_words("yes", _FALLBACK_YES)
    no_words = _confirm_words("no", _FALLBACK_NO)

    first_yes = first in yes_words or words[0] in yes_words
    first_no = first in no_words or words[0] in no_words
    has_marker = any(m in tail for m in _MODIFY_MARKERS)

    if first_yes and has_marker:
        return VoiceAnswer("modify", detail=norm, raw=raw)
    if first_no and has_marker:
        # "no, but make it five" — not a clean denial either; caller re-asks
        return VoiceAnswer("modify", detail=norm, raw=raw)
    if norm in yes_words or first_yes:
        return VoiceAnswer("yes", detail=norm, raw=raw)
    if norm in no_words or first_no:
        return VoiceAnswer("no", detail=norm, raw=raw)
    if has_marker:
        return VoiceAnswer("modify", detail=norm, raw=raw)
    return VoiceAnswer("unrecognized", detail=norm, raw=raw)


def to_confirm_answer(answer: VoiceAnswer, *, low_risk: bool) -> Optional[str]:
    """Map a parsed voice answer onto confirm.py's answer vocabulary.

    Returns 'yes' | 'no' | None:
      - low_risk=False (HIGH-risk confirmation) -> always None: voice is not
        an accepted channel there (brain-core's non-voice path decides).
      - low_risk=True, kind='yes'               -> 'yes'  (proceed)
      - low_risk=True, kind='no' | 'modify'     -> 'no'   (fail closed; a
        conditional is re-asked, never silently approved)
      - unrecognized                            -> None   (keep waiting; the
        confirmation timeout still ABORTS — never auto-approve)
    """
    if not low_risk:
        return None
    if answer.kind == "yes":
        return "yes"
    if answer.kind in ("no", "modify"):
        return "no"
    return None


# module-level convenience used by the ws.py wire-up (see docs/requests/)
def voice_confirmation_answer(text: str, *, low_risk: bool) -> Optional[str]:
    """One-call helper: transcript -> confirm answer or None (see above)."""
    return to_confirm_answer(parse_voice_answer(text), low_risk=low_risk)
