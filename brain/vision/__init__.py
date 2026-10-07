"""brain/vision — cloud-vision gate + see_screen service (computer-use lane).

Public surface:
  load_config / VisionConfig     — merged config (vision/privacy/jobs/profile)
  CloudVisionGate / Decision     — PROTOCOL §7 pre-send checklist
  redact_text                    — privacy.redact scrubbing
  jpeg_dimensions / within_max_px — downscale verification (fail closed)
  capture_screen / see_screen    — the gated screenshot→vision pipeline
  GateRefused                    — speakable gate denial

Nothing here writes images (or any screen bytes) to disk or logs.
"""
from .config import VisionConfig, load_config, load_raw
from .gate import CloudVisionGate, Decision
from .image import jpeg_dimensions, within_max_px
from .redact import redact_text
from .service import (GateRefused, capture_screen, default_config,
                      default_is_private, see_screen)

__all__ = [
    "VisionConfig", "load_config", "load_raw",
    "CloudVisionGate", "Decision",
    "redact_text", "jpeg_dimensions", "within_max_px",
    "capture_screen", "see_screen", "GateRefused",
    "default_config", "default_is_private",
]
