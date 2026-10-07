"""Strict JSON Schemas for the computer-use tools (INTERFACES §(b)).

Convention proposed to brain-core (docs/requests/computer-use__to__brain-core__
tool-integration-hooks.md): every tool package exposes `SPECS: dict[name ->
schema]` next to its register() calls; the auto-discovery loader validates each
entry (type object, typed properties, required listed, additionalProperties
false) and fails loudly on violations. These are validated in
tests/test_registry.py today.
"""
from __future__ import annotations

from typing import Any, Dict

SEE_SCREEN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "question about what is currently on the screen",
            "minLength": 1,
        }
    },
    "required": ["question"],
    "additionalProperties": False,
}

COMPUTER_USE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "description": "GUI task to accomplish, described by the user",
            "minLength": 1,
        }
    },
    "required": ["task"],
    "additionalProperties": False,
}

SPECS: Dict[str, Dict[str, Any]] = {
    "see_screen": SEE_SCREEN_SCHEMA,
    "computer_use": COMPUTER_USE_SCHEMA,
}
