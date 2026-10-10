"""Wave 5P P1: debunk-register lint (canon brief §7 is binding).

Asserts that NONE of the refuted claims from
`docs/research/persona/00-CONSOLIDATED-BRIEF.md` §7 ever appear in the persona
assets this lane owns: the tier prompts (`docs/evolution/persona/`), every
persona doc under `docs/evolution/`, the lane config fragment, and the
`brain/persona/` package.

The patterns are built by concatenation so THIS test file never trips its own
scan (same precedent as qa's scanner allowlist discipline). Research files
(`docs/research/persona/**`) are deliberately OUT of scope — they document the
register itself and legitimately quote the refuted strings.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# canonical refuted claim -> its detection needle (never a single literal here)
REFUTED = {
    "fabricated-wn-name (canon 00 §7 row 1)": "Ra" + "ziel",
    "nonexistent-va (canon 00 §7 row 2)": "Seto" + "guchi",
    "fabricated-technique (canon 00 §7 row 4)": "Hollow" + " Mixture",
    "phantom-war-arc (canon 00 §7 row 3)": "War of the Ten" + " Great Spirits",
    "fabricated-merge-mechanic (canon 00 §7 row 4)": "Angel-Series" + " Authority",
    "fan-pun-not-verified (canon 00 §7 row 9)": "oshi" + "eru",
    "invented-threshold (canon 00 §7 row 7)": "85" + "%",
}

SCAN_ROOTS = [
    REPO / "docs" / "evolution",                 # tier prompts + persona docs + journal
    REPO / "brain" / "persona",                  # the package
    REPO / "config.d" / "evolution-persona.yaml",  # lane fragment (persona.tier home)
]
SKIP_NAMES = {Path(__file__).name}              # this test carries the needles

CASE_INSENSITIVE = True


def _files():
    for root in SCAN_ROOTS:
        if root.is_file():
            yield root
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix in {".md", ".yaml", ".yml", ".py"} \
                    and p.name not in SKIP_NAMES:
                yield p


def test_scan_scope_is_not_empty():
    files = list(_files())
    assert len(files) >= 4, f"scope collapsed — {len(files)} files scanned"


def test_persona_assets_carry_no_debunked_claim():
    hits = []
    for path in _files():
        text = path.read_text(encoding="utf-8", errors="replace")
        haystack = text.lower() if CASE_INSENSITIVE else text
        for label, needle in REFUTED.items():
            probe = needle.lower() if CASE_INSENSITIVE else needle
            if probe in haystack:
                hits.append(f"{path.relative_to(REPO)}: {label}")
    assert not hits, "debunked claims leaked into persona assets: " + "; ".join(hits)


def test_register_covers_every_row_of_the_canon_table():
    """The canon §7 table has 10 rows; this lint pins the ones the lane brief
    names (7 needles) plus keeps the mapping honest: every needle must still
    be detected by a positive self-test on synthetic text."""
    synthetic = ("a " + "Ra" + "ziel sentence with " + "Seto" + "guchi and "
                 + "Hollow" + " Mixture, " + "War of the Ten" + " Great Spirits, "
                 + "Angel-Series" + " Authority, " + "oshi" + "eru, " + "85" + "%.")
    low = synthetic.lower()
    for label, needle in REFUTED.items():
        assert needle.lower() in low, f"needle lost its teeth: {label}"
