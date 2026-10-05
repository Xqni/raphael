"""Deterministic intent matcher (fast path).
Maps simple command strings to internal actions without LLM.
"""
from typing import Callable, Dict

_intents: Dict[str, Callable] = {}

def register_intent(keyword: str, handler: Callable):
    _intents[keyword.lower()] = handler

def match_intent(command: str):
    cmd = command.strip().lower()
    for kw, handler in _intents.items():
        if cmd.startswith(kw):
            return handler
    return None
