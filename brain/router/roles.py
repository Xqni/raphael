"""Live model discovery → role mapping (Wave 2 task 1).

NEVER hardcodes model IDs: providers fetch `GET /models` at call time and this
module scores whatever came back against configurable hint patterns
(`router.role_hints` in config.d/router.yaml). Hints are *capability words*
("instant", "70b", "vision", "whisper") — never exact IDs — so a renamed or
new model still maps correctly, and a vanished model is re-discovered rather
than being treated as an error (ARCHITECTURE §4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

ROLES = ("fast", "strong", "vision", "stt")

# capability words → role. Kept in code as the *default*; config can override
# per deployment without touching this file. Verified against the live lists
# on 2026-10-06 (Groq 11 models, Zen 88 models) — hints, never exact IDs.
DEFAULT_ROLE_HINTS: dict[str, list[str]] = {
    "fast": ["instant", "flash", "small", "tiny", "lite", "mini",
             "1b", "1.7b", "3b", "4b", "7b", "8b"],
    "strong": ["large", "plus", "pro", "max", "ultra", "9b", "12b", "24b",
               "27b", "32b", "70b", "90b", "120b"],
    "vision": ["vision", "llava", "multimodal", "-vl", "vl-", "maverick",
               "scout", "4a", "4u"],
    "stt": ["whisper", "distil-whisper", "speech-to-text"],
}

# Models that must NEVER land in a chat/vision slot even as a fallback:
# safety classifiers, TTS voices, embedders, moderation models (Groq's live
# list carries llama-prompt-guard, gpt-oss-safeguard and orpheus TTS).
DEFAULT_DENY_HINTS: list[str] = [
    "prompt-guard", "safeguard", "guard", "orpheus", "tts",
    "embed", "moderation", "rerank", "whisper",
]

# purpose (INTERFACES §a) → role. Usage tag only, but it picks the slot.
DEFAULT_PURPOSE_ROLES: dict[str, str] = {
    "chat": "fast",
    "tool": "strong",
    "plan": "strong",
    "ack": "fast",
    "vision": "vision",
}


@dataclass(frozen=True)
class ModelInfo:
    id: str
    provider: str
    free: bool = True
    paid: bool = False
    capabilities: frozenset[str] = frozenset()
    meta: dict = field(default_factory=dict)

    def has(self, cap: str) -> bool:
        return cap in self.capabilities


def score_model(model_id: str, hints: dict[str, list[str]]) -> dict[str, int]:
    """Per-role match score for one model id (higher = better fit)."""
    mid = model_id.lower()
    scores: dict[str, int] = {}
    for role in ROLES:
        words = hints.get(role) or []
        score = 0
        for word in words:
            w = str(word).lower()
            if not w:
                continue
            if w in mid:
                # longer (more specific) hint matches weigh a bit more
                score += 10 + min(len(w), 12)
        scores[role] = score
    return scores


def pick(
    models: Sequence[ModelInfo],
    role: str,
    hints: dict[str, list[str]] | None = None,
    *,
    require_capability: str | None = None,
    deny_hints: Sequence[str] | None = None,
) -> ModelInfo | None:
    """Best model for `role`, or None when nothing can serve it.

    Rules (deterministic, discovery-driven):
      0. deny-hinted models (classifiers/TTS/embedders) never serve a
         chat/vision slot, not even as a fallback;
      1. explicit capability metadata from the provider wins
         (e.g. Ollama tags capabilities: ["vision", "tools"]);
      2. otherwise the highest hint score wins (ties → first seen);
      3. `fast`/`strong` fall back to shortest/longest id (name length is a
         crude but stable size proxy) so chat never dead-ends on an unknown
         naming scheme;
      4. `vision`/`stt` fall back to None — we never send an image or audio
         to a model that never claimed the capability.
    """
    if not models:
        return None
    hints = hints or DEFAULT_ROLE_HINTS
    deny = list(DEFAULT_DENY_HINTS if deny_hints is None else deny_hints)
    if role in ("fast", "strong", "vision") and deny:
        low = [d.lower() for d in deny if d]
        models = [m for m in models
                  if not any(d in m.id.lower() for d in low)]
        if not models:
            return None
    cap_for_role = {"vision": "vision", "stt": "audio"}.get(role)
    cap = require_capability or cap_for_role
    if cap == "stt":
        cap = "audio"  # role/requirement name vs provider capability name

    candidates = [m for m in models if (cap is None or m.has(cap) or not m.capabilities)]
    if not candidates:
        return None
    if cap and any(m.has(cap) for m in candidates):
        candidates = [m for m in candidates if m.has(cap)]

    scored: list[tuple[int, int, ModelInfo]] = []
    for idx, m in enumerate(candidates):
        s = score_model(m.id, hints).get(role, 0)
        if cap and m.has(cap):
            s += 50  # provider told us directly
        scored.append((s, idx, m))
    best = max(s for s, _, _ in scored)
    if best > 0:
        top = [m for s, _, m in scored if s == best]
        return top[0]
    if role == "fast":
        return min(candidates, key=lambda m: len(m.id))
    if role == "strong":
        return max(candidates, key=lambda m: len(m.id))
    return None


def free_only(models: Iterable[ModelInfo]) -> list[ModelInfo]:
    """Free models only — paid-pool models are never selected (§7 money gate)."""
    return [m for m in models if m.free and not m.paid]
