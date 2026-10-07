"""Cloud-vision gate — the PROTOCOL §7 pre-send checklist, enforced in code.

Order of checks for `see_screen` (deny short-circuits BEFORE capture when
possible — never even capture what we already know we may not send):

  1. Private Mode            -> deny  (§7(5): private disables ALL model calls)
  2. profile/provider legality -> deny (§7(1): cloud ONLY under profile cloud_temp)
  3. foreground blocklist    -> deny  (§7(2): privacy.blocklist_apps match)
  4. screenshot capture via Body (downscale requested: max_px/quality)
  5. downscale verification  -> deny  (§7: fail closed if image > max_px / unparseable)
  6. router.vision call (never logged, never persisted — debug_capture stays false)
  7. redact extracted text   ->       (§7(3): privacy.redact before anything leaves)

Every denial carries a SHORT human reason suitable for speaking (the brief asks
for "a short explanation"). Code names are stable for tests/logs; reasons are
what the user hears. Gate code NEVER raises on bad input — it refuses.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import VisionConfig
from .image import within_max_px
from .redact import redact_text

# Stable refusal codes (test + journal use; not PROTOCOL wire codes — these
# never cross the WS as `error.code`, they are local gate verdicts).
E_PRIVATE = "E_PRIVATE"
E_PROFILE = "E_PROFILE"
E_BLOCKED = "E_BLOCKED"
E_NO_FOREGROUND = "E_NO_FOREGROUND"
E_TOO_LARGE = "E_TOO_LARGE"
E_EMPTY_IMAGE = "E_EMPTY_IMAGE"


@dataclass(frozen=True)
class Decision:
    ok: bool
    code: str = ""
    reason: str = ""          # short, speakable explanation ("" when ok)

    @classmethod
    def allow(cls) -> "Decision":
        return cls(True)

    @classmethod
    def deny(cls, code: str, reason: str) -> "Decision":
        return cls(False, code=code, reason=reason)


class CloudVisionGate:
    """Stateless PROTOCOL §7 gate over the effective config."""

    def __init__(self, config: Optional[VisionConfig] = None):
        self.config = config if config is not None else VisionConfig()

    # ---- 1. private mode ---------------------------------------------------
    def check_private(self, is_private: bool) -> Decision:
        if is_private:
            return Decision.deny(E_PRIVATE,
                                 "Private mode is on — screen access is off.")
        return Decision.allow()

    # ---- 2. profile / provider --------------------------------------------
    def check_profile(self) -> Decision:
        cfg = self.config
        if cfg.provider != "cloud":
            return Decision.allow()            # local vision (Wave 6 path) — no egress
        if not cfg.cloud_allowed:
            return Decision.deny(
                E_PROFILE,
                f"Cloud vision isn't allowed in profile {cfg.profile} — "
                "screenshots stay on this machine.")
        return Decision.allow()

    # ---- 3. foreground blocklist -------------------------------------------
    def matched_blocklist_app(self, title: Optional[str]) -> Optional[str]:
        """First privacy.blocklist_apps entry matching the foreground title
        (case-insensitive substring). None = no match."""
        if title is None:
            return None
        hay = str(title).casefold()
        for app in self.config.blocklist_apps:
            token = str(app).strip()
            if token and token.casefold() in hay:
                return token
        return None

    def check_foreground(self, title: Optional[str]) -> Decision:
        """Fail CLOSED: an unknown foreground title (None) cannot be checked,
        so no screenshot may leave the machine."""
        if title is None:
            return Decision.deny(
                E_NO_FOREGROUND,
                "I can't verify which window is in front, so I won't send "
                "a screenshot.")
        hit = self.matched_blocklist_app(title)
        if hit is not None:
            return Decision.deny(
                E_BLOCKED,
                f"A sensitive window ({hit}) is in front — I won't send the "
                "screen anywhere.")
        return Decision.allow()

    # ---- 5. downscale verification -----------------------------------------
    def check_image(self, data: Optional[bytes]) -> Decision:
        if not data:
            return Decision.deny(E_EMPTY_IMAGE,
                                 "The screenshot came back empty — try again.")
        if not within_max_px(data, self.config.max_px):
            return Decision.deny(
                E_TOO_LARGE,
                "The screenshot is larger than the size limit or unreadable — "
                "refusing to send it.")
        return Decision.allow()

    # ---- 7. redaction -------------------------------------------------------
    def redact(self, text: str) -> str:
        return redact_text(text, self.config.redact)
