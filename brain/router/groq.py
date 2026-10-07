"""Groq provider (profile `cloud_temp` first choice).

OpenAI-compatible endpoint `https://api.groq.com/openai/v1`, key from
`GROQ_API_KEY` in `.env` (presence-checked value-blind, never logged).

Model IDs are NEVER hardcoded: `GET /models` is fetched live and the role
mapper (roles.py) scores the returned ids against `router.role_hints`
(config.d/router.yaml) to fill the four slots — fast router model, stronger
tool-calling chat model, vision model, Whisper STT model.
"""
from __future__ import annotations

from .config import RouterConfig
from .openai_compat import OpenAICompatProvider


class GroqProvider(OpenAICompatProvider):
    def __init__(self, config: RouterConfig) -> None:
        super().__init__(
            config,
            name="groq",
            base_url=config.providers.groq_base_url,
            key_env=config.providers.groq_key_env,
            # capability slots: chat/tools/vision on the chat side,
            # "stt" = Whisper (matched live via router.role_hints.stt)
            caps=frozenset({"chat", "tools", "vision", "stt"}),
        )
