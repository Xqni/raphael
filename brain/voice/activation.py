"""brain/voice/activation.py — activation policy for the mic lane
(voice lane, Wave 2 task 2).

Two decisions, in order:

1. PRE-STT (`ActivationGate.should_transcribe`) — may this segment be sent to
   cloud STT at all? Local, free, no model:
     - silent / too-short segments  -> never (answered locally as '')
     - `reason='ptt'` (hotkey)      -> always (the keypress IS the intent)
     - `reason='wake'` with `voice.always_listen: false` -> never: PTT-only
       mode (the body already stops its wake stream in that mode — this is
       the brain-side double-check for callers that pass the reason)
   The phonetic wake gate itself works on TRANSCRIPTS, so the final
   "is this her" decision is made right after STT (see 2 + wake.WakeGate).
   Cost control comes from: VAD segmentation on the body (one utterance = one
   call), this pre-gate, the silence short-circuit in stt.py, and the body's
   echo guard (body/win/audio_in.py) that keeps her own playback from opening
   segments while she speaks.

2. POST-STT (`ActivationGate.gate`) — does the transcript count as a command?
   Delegates to the existing phonetic WakeGate (filler-tolerant, ASR-fold
   matching) and additionally rejects PLAYBACK ECHOES: anything matching what
   Raphael said in the last few seconds is her own voice bouncing off the
   speakers, not the user — this is what breaks the self-trigger loop
   ("Raphael online." greeting -> mic -> STT -> wake gate -> new job).
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Tuple

from .config import VoiceConfig, load_voice_config
from .stt import (STT_SAMPLE_RATE, TranscribeResult, is_effectively_silent)
from .wake import WakeGate, WakeMatch, normalize_text


@dataclass
class GateDecision:
    """why behind a should_transcribe() answer (logged/tested, never secret)."""
    ok: bool
    reason: str                 # 'ptt' | 'wake' | 'silence' | 'ptt_only' | ...

    def __bool__(self) -> bool:  # `if gate.should_transcribe(...):`
        return self.ok


# ---- playback echo registry ------------------------------------------------
class PlaybackEchoRegistry:
    """What Raphael has just said, for echo rejection after STT.

    Bounded (last N utterances) with a TTL: a transcript that substantially
    matches her recent speech is her own playback reaching the mic.
    Short transcripts (<=2 words) are NEVER treated as echoes so that
    "yes"/"no"/single-word commands from the user always get through.
    """

    MIN_ECHO_WORDS = 3
    FUZZY_RATIO = 0.85
    TTL_S = 120.0

    def __init__(self, maxlen: int = 8):
        self._items: Deque[Tuple[str, float]] = deque(maxlen=maxlen)

    def remember(self, text: str) -> None:
        norm = normalize_text(text)
        if norm:
            self._items.append((norm, time.monotonic()))

    def clear(self) -> None:
        self._items.clear()

    def recent(self) -> List[str]:
        now = time.monotonic()
        return [t for t, ts in self._items if now - ts <= self.TTL_S]

    @classmethod
    def _fuzzy_hit(cls, transcript: str, spoken: str) -> bool:
        from difflib import SequenceMatcher

        tt, st = transcript.split(), spoken.split()
        if len(tt) < cls.MIN_ECHO_WORDS:
            return False
        if len(tt) > len(st):
            return SequenceMatcher(None, transcript, spoken).ratio() >= 0.95
        # slide a window of the transcript's length over her utterance
        win = len(tt)
        for i in range(0, len(st) - win + 1):
            window = " ".join(st[i:i + win])
            if SequenceMatcher(None, window, transcript).ratio() >= cls.FUZZY_RATIO:
                return True
        return False

    def is_echo(self, transcript: str) -> bool:
        t = normalize_text(transcript)
        if len(t.split()) < self.MIN_ECHO_WORDS:
            return False                            # short = user's, never echo
        for spoken in self.recent():
            if t in spoken or spoken in t:
                return True
            if self._fuzzy_hit(t, spoken):
                return True
        return False


_ECHOES = PlaybackEchoRegistry()


def get_playback_echoes() -> PlaybackEchoRegistry:
    """Module singleton — tts.py remembers, wake/activation consults."""
    return _ECHOES


# ---- the gate --------------------------------------------------------------
class ActivationGate:
    """Pre-STT + post-STT activation policy (see module docstring)."""

    def __init__(self, cfg: Optional[VoiceConfig] = None,
                 wake: Optional[WakeGate] = None):
        self.cfg = cfg or load_voice_config()
        self.wake = wake or WakeGate(self.cfg.wake_word)
        self.echoes = get_playback_echoes()

    def __getattr__(self, name: str) -> Any:
        """Duck-type as the underlying WakeGate (matches_wake/extract/...),
        so callers written against WakeGate keep working."""
        if name.startswith("_"):
            raise AttributeError(name)
        wake = self.__dict__.get("wake")
        if wake is None:
            raise AttributeError(name)
        return getattr(wake, name)

    # -- 1. pre-STT ---------------------------------------------------------
    def should_transcribe(self, pcm: bytes, reason: Optional[str] = None,
                          sample_rate: int = STT_SAMPLE_RATE) -> GateDecision:
        """May this segment go to the cloud STT engine?

        SEC-3 (Wave 5H) FAIL-CLOSED: audio is uploaded ONLY with an explicit
        verdict — `reason='ptt'` (hotkey) or `reason='wake'` (always-listen
        VAD segment). Any UNDECIDED state (reason missing/unknown, or an
        unexpected error inside the gate) DISCARDS the segment locally: it
        never reaches a provider and never touches disk.

        The previous implementation failed open on both paths
        (`return GateDecision(True, reason or "unknown")` and
        `return GateDecision(True, "error_fail_open")`) — a buggy or
        miswired caller would have shipped every VAD segment to cloud STT
        before any wake check. Silence still short-circuits first (cheapest,
        no verdict needed to DROP).
        """
        try:
            if is_effectively_silent(pcm, sample_rate):
                return GateDecision(False, "silence")
            if reason == "ptt":
                return GateDecision(True, "ptt")     # hotkey = proven intent
            if reason == "wake":
                if not self.cfg.always_listen:
                    # PTT-only profile: wake segments are not expected at all
                    return GateDecision(False, "ptt_only")
                return GateDecision(True, "wake")
            # SEC-3: undecided (reason is None / unknown / anything else)
            # -> NO upload without a wake/ptt verdict
            return GateDecision(False, f"undecided:{reason!r}")
        except Exception as e:  # noqa: BLE001 — but never fail OPEN
            print(f"[voice] activation gate error — segment discarded "
                  f"(SEC-3 fail-closed): {type(e).__name__}: {e}", flush=True)
            return GateDecision(False, "error_fail_closed")

    # -- 2. post-STT --------------------------------------------------------
    def gate(self, transcript: str, reason: str = "wake") -> WakeMatch:
        """Transcript -> WakeMatch, with playback-echo rejection applied first."""
        if self.echoes.is_echo(transcript):
            return WakeMatch(kind="none", reason=reason,
                             raw=(transcript or "").strip())
        return self.wake.gate(transcript, reason=reason)


# module-level singleton (VoiceStack wires it)
_gate: Optional[ActivationGate] = None


def get_activation(cfg: Optional[VoiceConfig] = None) -> ActivationGate:
    global _gate
    if _gate is None:
        _gate = ActivationGate(cfg)
    return _gate


def reset_activation() -> None:
    """Test hook."""
    global _gate
    _gate = None
    _ECHOES.clear()
