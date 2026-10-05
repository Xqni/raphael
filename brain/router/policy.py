"""Model selection policy — permanent exclusions enforced at every selection point.

Source: docs/REQUIREMENTS_ADDENDUM.md + config.yaml (user directive: fun-only model,
permanently excluded from local_model_candidates, benchmarks, and vision slots).
Kept as a dependency-free leaf module so zen.py / ollama.py / core.py can all import
it without cycles.
"""
from __future__ import annotations

# Lowercase base names (match also via ':'-family split, e.g. "slut:latest").
EXCLUDED_MODEL_IDS = frozenset({"slut"})


def is_excluded(model_id: str) -> bool:
    """True if a model id is permanently excluded from runtime selection."""
    if not model_id:
        return False
    name = model_id.strip().lower()
    base = name.split(":", 1)[0]
    return name in EXCLUDED_MODEL_IDS or base in EXCLUDED_MODEL_IDS
