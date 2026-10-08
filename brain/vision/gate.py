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

import re
from dataclasses import dataclass
from typing import Optional, Tuple

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
E_UNREACHABLE = "E_UNREACHABLE"   # Body/probe unreachable — NOT a privacy verdict
E_DEBUG_CAPTURE = "E_DEBUG_CAPTURE"  # §7(4): cloud send needs debug_capture false
E_SENSITIVE = "E_SENSITIVE"       # sensitive context beyond the static blocklist

# Wave 5H item 2 — short spoken reason for focused-password refusals.
PASSWORD_FOCUS_REASON = ("A password field is focused — I won't capture "
                         "the screen.")

# Wave 5H item 2 — DEFAULT sensitive-context patterns (merged with the
# configurable `computer_use.sensitive_title_patterns` from config.d).
# UAC/secure-desktop + credential surfaces that are NOT in privacy.blocklist_apps.
DEFAULT_SENSITIVE_PATTERNS: Tuple[str, ...] = (
    "user account control",     # UAC prompt
    "consent.exe",              # UAC broker process
    "credentialui",             # credential picker
    "windows security",
    "smartcard",
    "bank",                     # configurable-class defaults (audit: bank/wallet/2FA)
    "wallet",
    "2fa",
    "two-factor",
    "authenticator",
    "one-time code", "otp code",
)


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
        if cfg.provider == "local":
            return Decision.allow()            # local vision (Wave 6 path) — no egress
        if cfg.provider != "cloud":
            # Wave 5H item 1: NO cloud-vision policy configured (''/none/typo)
            # = no policy to enforce = fail closed, never "call and see".
            return Decision.deny(
                E_PROFILE,
                "No cloud-vision policy is configured for this instance — "
                "I won't send screenshots anywhere.")
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
        so no screenshot may leave the machine. Beyond the static blocklist,
        ALSO matches the sensitive-context patterns (Wave 5H item 2): UAC/
        secure-desktop prompts and configurable bank/wallet/2FA titles —
        refused with a short spoken reason."""
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
        hit = self.matched_sensitive_pattern(title)
        if hit is not None:
            return Decision.deny(
                E_SENSITIVE,
                f"A sensitive context ({hit}) is in front — I won't send the "
                "screen anywhere.")
        return Decision.allow()

    # ---- 2b. sensitive contexts beyond the static blocklist (Wave 5H) -------
    def sensitive_patterns(self) -> Tuple[str, ...]:
        """UAC/credential defaults UNION the configurable
        `computer_use.sensitive_title_patterns` (config.d/<lane>.yaml — the
        lane's own namespace, not authority-guarded)."""
        return tuple(dict.fromkeys(
            DEFAULT_SENSITIVE_PATTERNS + tuple(self.config.sensitive_patterns)))

    @staticmethod
    def _pattern_hit(pattern: str, hay: str) -> bool:
        """Case-insensitive REGEX when valid, literal substring otherwise —
        a bad config pattern can never crash the gate or match everything."""
        pat = str(pattern).strip()
        if not pat:
            return False
        try:
            return re.search(pat, hay, re.IGNORECASE) is not None
        except re.error:
            return pat.casefold() in hay

    def matched_sensitive_pattern(self, identity: str) -> Optional[str]:
        hay = str(identity or "").casefold()
        if not hay:
            return None
        for pattern in self.sensitive_patterns():
            if self._pattern_hit(pattern, hay):
                return str(pattern).strip()
        return None

    # ---- probe failures (Bug F: honest verdicts) -----------------------------
    @staticmethod
    def unreachable(detail: str = "") -> Decision:
        """The Body/capture path could not be REACHED (probe raised — body
        session gone, act timeout, unsupported op). Fail closed with an
        HONEST, distinguishable message: this is an availability problem, not
        the privacy verdict of E_NO_FOREGROUND (Bug F: a mid-restart body
        disconnect was being reported as 'can't verify which window')."""
        hint = " ".join(str(detail).split())[:60]
        suffix = f" ({hint})" if hint else ""
        return Decision.deny(
            E_UNREACHABLE,
            f"I can't reach the Body right now{suffix} — try again in a moment.")

    @staticmethod
    def err_hint(e: BaseException) -> str:
        """Short, speech-safe hint for a failed probe: structured detail/code
        when the exception carries one, else just the type name. Never raw
        str(e) (arbitrary text must not reach speech/journal)."""
        for attr in ("detail", "code"):
            val = getattr(e, attr, None)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return type(e).__name__

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

    # ---- 4. debug capture (PROTOCOL §7 condition (4)) -----------------------
    def check_debug_capture(self) -> Decision:
        """Cloud egress requires `privacy.debug_capture: false` (the image is
        never logged/persisted). Enforced IN CODE, never assumed — qa-security
        request …__vision-gate.md item 4. Local vision (profile local) is
        unaffected: the image never leaves the machine either way."""
        cfg = self.config
        if cfg.provider != "cloud":
            return Decision.allow()
        if cfg.debug_capture:
            return Decision.deny(
                E_DEBUG_CAPTURE,
                "Screenshot debugging is on — screenshots stay on this "
                "machine.")
        return Decision.allow()

    # ---- 7. redaction -------------------------------------------------------
    def redact(self, text: str) -> str:
        return redact_text(text, self.config.redact)
