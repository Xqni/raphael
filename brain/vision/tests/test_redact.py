"""redact_text — privacy.redact scrubbing (PROTOCOL §7 condition (3))."""
from brain.vision.redact import available_kinds, redact_text

ALL = ("api_key", "token", "password", "card", "email", "phone")


def test_masks_every_configured_kind():
    text = ("api_key=sk-abcdef123456 token: eyJhbGciOiJIUzI1NiJ9."
            "eyJzdWIiOiIxIn0.abcdefgh12345678 password=hunter2 "
            "card 4111 1111 1111 1111 mail me@example.com call +1 416 555 0123")
    out = redact_text(text, ALL)
    assert "sk-abcdef123456" not in out
    assert "eyJhbGciOiJIUzI1NiJ9" not in out
    assert "hunter2" not in out
    assert "4111" not in out
    assert "me@example.com" not in out
    assert "416 555 0123" not in out
    assert out.count("[REDACTED:") >= 6


def test_only_configured_kinds_are_scrubbed():
    text = "mail me@example.com phone +1 416 555 0123"
    out = redact_text(text, ["email"])
    assert "[REDACTED:email]" in out
    assert "416 555 0123" in out        # phone untouched (not configured)


def test_clean_text_unchanged_and_empty_kinds():
    text = "The Save button is in the toolbar."
    assert redact_text(text, ALL) == text
    assert redact_text(text, []) == text
    assert redact_text("", ALL) == ""
    assert redact_text(None, ALL) == ""


def test_unknown_kind_ignored():
    text = "mail me@example.com"
    assert redact_text(text, ["carrier_pigeon"]) == text


def test_dates_are_not_phone_redacted():
    text = "created 2026-10-05 build 3"
    assert redact_text(text, ["phone"]) == text


def test_available_kinds_covers_config():
    assert set(ALL) <= set(available_kinds())
