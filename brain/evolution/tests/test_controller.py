"""Controller unit tests — the pure mode/zone gate (F-1: propose NEVER promotes)."""
import pytest

from brain.evolution.controller import decide
from brain.evolution.zones import Zone


@pytest.mark.parametrize("mode,zone,expect", [
    ("propose", Zone.MUTABLE, "proposal"),
    ("propose", Zone.CORE, "proposal"),      # propose is proposal-only, always
    ("auto_safe", Zone.MUTABLE, "promote"),  # the ONLY promote combination
    ("auto_safe", Zone.CORE, "proposal"),    # core never auto-promotes
    ("off", Zone.MUTABLE, "skip"),
    ("off", Zone.CORE, "skip"),
    ("banana", Zone.MUTABLE, "skip"),        # unknown mode = no action
    (None, Zone.MUTABLE, "skip"),
])
def test_mode_zone_gate(mode, zone, expect):
    assert decide(mode, zone) == expect


def test_promote_requires_everything():
    """Exactly one path reaches promote; everything else is proposal/skip."""
    promotes = [decide(m, z) for m in ("propose", "auto_safe", "off", "x")
                for z in (Zone.CORE, Zone.MUTABLE)]
    assert promotes.count("promote") == 1
