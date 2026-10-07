"""brain/voice/wake.py — wake word, PTT gating, barge-in interrupts (voice-dev).

Phase-1 ships the *logic* (pure, unit-testable, no audio hardware needed);
phase-2 wires it to the live mic lane in ws.py (audio_start/end handlers).

Wake word (config voice.wake_word, default "raphael"): a `wake`-reason
utterance must START with the wake word; the command is the remainder.
A `ptt`-reason utterance is taken as-is (push-to-talk already proves intent).
Barge-in: when audio arrives while Raphael is speaking, InterruptController
cancels the in-flight speak stream immediately (PROTOCOL §5: control returns
to the listener; the engine drops stale TTS chunks).
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s']+", re.UNICODE)


def normalize_text(text: str) -> str:
    """Cache/compare normalization: NFKC, lowercase, strip punctuation,
    collapse whitespace."""
    t = unicodedata.normalize("NFKC", text or "")
    t = t.lower().strip()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


@dataclass
class WakeMatch:
    kind: str                 # 'wake' | 'ptt' | 'none'
    command: str = ""         # text with the wake word stripped (wake kind)
    reason: str = ""          # 'wake' | 'ptt' (audio_start.reason)
    raw: str = ""


class WakeGate:
    """Determines whether an utterance is a command, and extracts it.

    reason='ptt'  -> command = transcript as-is (any text).
    reason='wake' -> must start with wake word (normalized); command = rest.
                     leading filler ("hey", "ok", "please") is tolerated.
    """

    FILLER = {"hey", "hi", "ok", "okay", "please", "yo", "so",
              "um", "uh", "uhm", "eh", "ah"}
    # ASR tolerance: the live digital wake test showed whisper renders
    # "Raphael" as "Rafael" — exact matching rejected a perfect utterance.
    # 0.82 fuzzy ratio accepts homophone spellings, rejects real non-words
    # ("banana" ~0.38, "rachel" ~0.55 vs wake "raphael").

    def __init__(self, wake_word: str = "raphael"):
        self.wake_word = normalize_text(wake_word) or "raphael"

    @staticmethod
    def _fold(word: str) -> str:
        """Phonetic fold for homophone spellings (ASR renders 'Raphael' as
        'Rafael'). Plain fuzzy ratio CANNOT discriminate: difflib gives
        rafael/raphael 0.77 AND rachel/raphael ~0.77 — folding does:
        raphael->rafael == rafael ✓, rachel->racel ≠ rafael ✓ rejected."""
        return word.replace('ph', 'f').replace('h', '')

    def _is_wake(self, word: str) -> bool:
        if word == self.wake_word:
            return True
        if len(word) >= 4 and len(self.wake_word) >= 4:
            if self._fold(word) == self._fold(self.wake_word):
                return True
            import difflib
            return (difflib.SequenceMatcher(None, word, self.wake_word)
                    .ratio() >= 0.90)  # only near-identical extras pass
        return False

    def matches_wake(self, transcript: str) -> bool:
        """True when transcript begins with the wake word (filler + ASR
        spelling variance tolerated)."""
        words = normalize_text(transcript).split()
        if not words:
            return False
        i = 0
        while i < len(words) and words[i] in self.FILLER:
            i += 1
        return i < len(words) and self._is_wake(words[i])

    def extract(self, transcript: str) -> str:
        """Strip wake word(s) + filler prefix -> the command remainder.

        Strips ALL leading wake/filler words (live gate 2026-10-07: a repeated
        wake word left one copy in the command, which broke intent matching)."""
        words = normalize_text(transcript).split()
        i = 0
        while i < len(words) and (words[i] in self.FILLER or self._is_wake(words[i])):
            i += 1
        return " ".join(words[i:])

    def gate(self, transcript: str, reason: str = "wake") -> WakeMatch:
        raw = (transcript or "").strip()
        norm = normalize_text(raw)
        if not norm:
            return WakeMatch(kind="none", reason=reason, raw=raw)
        if reason == "ptt":
            return WakeMatch(kind="ptt", command=norm, reason=reason, raw=raw)
        if self.matches_wake(raw):
            return WakeMatch(kind="wake", command=self.extract(raw),
                             reason="wake", raw=raw)
        return WakeMatch(kind="none", reason=reason, raw=raw)


class PTTGate:
    """Push-to-talk state: audio_start{reason:'ptt'} opens the gate until
    audio_end. Phase-2 wires this to the real frames; logic is here."""

    def __init__(self):
        self._active: Set[str] = set()   # session ids currently in PTT

    def open(self, sid: str, reason: str = "ptt") -> bool:
        """Called on audio_start. True when mic frames should be buffered."""
        if reason not in ("ptt", "wake"):
            return False
        self._active.add(sid)
        return True

    def close(self, sid: str) -> None:
        self._active.discard(sid)

    def is_active(self, sid: str) -> bool:
        return sid in self._active


class InterruptController:
    """Barge-in: cancel in-flight speech the moment the user speaks.

    loop.py: on any new `command`/`audio_start` while a speak stream is
    running, call interrupt(job_or_all) BEFORE submitting the new work.
    The speak() async iterator checks its cancel event between chunks and
    terminates with an `interrupted` end event (PROTOCOL §5 semantics:
    queued announcements never interrupt mid-sentence — only USER voice does).
    """

    def __init__(self):
        self._events: Dict[str, asyncio.Event] = {}
        self._all: Optional[asyncio.Event] = None

    def register(self, key: str) -> asyncio.Event:
        ev = self._events.get(key)
        if ev is None or ev.is_set():
            ev = asyncio.Event()
            self._events[key] = ev
        return ev

    def interrupt(self, key: Optional[str] = None) -> int:
        """Cancel one stream (key) or ALL streams (key=None). Returns count."""
        n = 0
        if key is None:
            for ev in self._events.values():
                if not ev.is_set():
                    ev.set()
                    n += 1
            self._events.clear()
            return n
        ev = self._events.pop(key, None)
        if ev is not None and not ev.is_set():
            ev.set()
            n += 1
        return n

    def done(self, key: str) -> None:
        self._events.pop(key, None)

    def any_active(self) -> bool:
        return bool(self._events)


# module-level singleton (loop.py integration)
_gate: Optional[WakeGate] = None
_interrupts: Optional[InterruptController] = None
_ptt: Optional[PTTGate] = None


def get_wake_gate(wake_word: str = "raphael") -> WakeGate:
    global _gate
    if _gate is None:
        _gate = WakeGate(wake_word)
    return _gate


def get_interrupts() -> InterruptController:
    global _interrupts
    if _interrupts is None:
        _interrupts = InterruptController()
    return _interrupts


def get_ptt_gate() -> PTTGate:
    global _ptt
    if _ptt is None:
        _ptt = PTTGate()
    return _ptt
