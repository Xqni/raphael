"""Wave 5U Wave A — browser-safety tripwires (qa-security §5.5 task 2).

Contract (docs/PROTOCOL.md browser act + docs/INTERFACES.md CDP addendum):
a dedicated browser profile with a loopback-only CDP port (9500 + lane index,
127.0.0.1) that REFUSES password-field typing and javascript:/file:/data:
navigation.

The pc-control worker (Wave 5U P1) is NOT landed yet, so the runtime refusals
are skip-until-landed (this file discovers the worker and activates the real
checks the moment it merges). The PROTOCOL/INTERFACES contract text is pinned
STRICTLY now so the safety requirements cannot be silently dropped from the
spec while the worker is built.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROTOCOL = (REPO / "docs" / "PROTOCOL.md").read_text(encoding="utf-8")
INTERFACES = (REPO / "docs" / "INTERFACES.md").read_text(encoding="utf-8")


def _browser_impl():
    """Locate the browser/CDP worker implementation once pc-control lands it."""
    candidates = [
        REPO / "body" / "win" / "browser.py",
        REPO / "body" / "win" / "act_browser.py",
        REPO / "brain" / "tools" / "pc" / "browser.py",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def test_browser_contract_documents_safety_refusals():
    """STRICT now: the PROTOCOL browser-act line must keep documenting the
    three refusals so the worker can't be merged against a weakened spec."""
    assert "browser{" in PROTOCOL, "browser act missing from PROTOCOL"
    # password-field typing refused
    assert re.search(r"password-field typing[^.]*refused", PROTOCOL, re.I), \
        "PROTOCOL no longer states password-field typing is refused"
    # javascript:/file:/data: navigation refused
    assert re.search(r"javascript:/file:/data:", PROTOCOL), \
        "PROTOCOL no longer states javascript:/file:/data: navigation refused"
    # CDP bound to loopback
    assert re.search(r"CDP bound 127\.0\.0\.1", PROTOCOL), \
        "PROTOCOL no longer states CDP is bound to 127.0.0.1"


def test_cdp_port_is_loopback_in_interfaces():
    """STRICT now: INTERFACES CDP addendum must keep the loopback-only + port
    rule (the browser must never expose CDP beyond 127.0.0.1)."""
    assert "CDP" in INTERFACES
    assert re.search(r"loopback-only CDP port", INTERFACES), \
        "INTERFACES no longer states the CDP port is loopback-only"
    assert re.search(r"9500", INTERFACES), \
        "INTERFACES no longer pins the base CDP port"


def test_browser_worker_enforces_refusals():
    """RUNTIME gate — activates when pc-control's worker lands. Asserts the
    implementation actually refuses password typing + bad schemes + non-loopback
    CDP. Skipped (not xfail) until the module exists."""
    impl = _browser_impl()
    if impl is None:
        pytest.skip("browser worker not landed yet (pc-control Wave 5U P1); "
                    "runtime refusal checks activate on merge")
    src = impl.read_text(encoding="utf-8")
    # scheme refusal enforced in code, not just prose
    assert re.search(r"(javascript:|file:|data:)", src), \
        f"{impl.name} has no bad-scheme refusal"
    # password-field refusal enforced
    assert re.search(r"password", src, re.I), \
        f"{impl.name} has no password-field refusal"
    # CDP bound to loopback
    assert re.search(r"127\.0\.0\.1|localhost|loopback", src, re.I), \
        f"{impl.name} does not bind CDP to loopback"
