"""Wave 5P — debunk-register lint + mutation check (qa-security packet 2).

Packet law (docs/lanes/qa-security.md Wave 5P, line 2): "the persona lint
test must actually fail on a refuted string (mutation-check it)".

What this file enforces:
1. The binding register (00-CONSOLIDATED-BRIEF.md §7, all 10 rows) is encoded
   as scannable patterns — no refuted claim may appear in PERSONA ASSETS:
   `config.yaml` (voice_personality/persona text), `brain/persona/**` and
   `docs/evolution/persona/**` (tier prompts, when evolution-persona authors
   them). Design docs and tests are OUT OF scope on purpose: the register
   itself is quoted legitimately in docs/research/persona/ and here.
2. Mutation self-check (strict, runs today): every registered pattern must
   actually FLAG its planted refuted sentence, and a canon-safe paragraph must
   pass — proving this lint really fails on a refuted string.
3. Mutation check of THE lint test itself (auto-activates when landed): once
   evolution-persona's P1 debunk lint exists AND persona assets exist, this
   test runs their lint on clean assets (must pass), then plants a refuted
   string in the persona asset dir (their lint must FAIL) — skip-with-reason
   until both preconditions hold (lanes land in any order).
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# (claim from §7 register, [(pattern, planted sentence), ...])
REFUTED = [
    ("Raziel (WN-name fabrication)",
     [(r"Raziel", "The WN chapter used the name Raziel.")]),
    ("Megumi Setoguchi VA (does not exist)",
     [(r"Setoguchi", "Voice actress Megumi Setoguchi voiced the role.")]),
    ("War of the Ten Great Spirits (phantom arc)",
     [(r"Ten\s+Great\s+Spirits",
       "The War of the Ten Great Spirits arc opens the finale.")]),
    ("Great Sage merged with an Angel-Series Authority Ciel",
     [(r"Angel-Series",
       "Great Sage merged with an Angel-Series Authority to become Ciel.")]),
    ("Raphael named after the Clayman battle (Vol 14) — wrong era",
     [(r"named[^.\n]{0,40}Clayman",
       "Raphael was named right after the Clayman battle."),
      (r"Clayman battle", "the Clayman battle era")]),
    ("Hollow Mixture (fabricated technique)",
     [(r"Hollow\s+Mixture", "The Hollow Mixture technique was unleashed.")]),
    ("85% fatal-probability autonomy threshold (invented)",
     [(r"85\s*%\s*fatal",
       "An 85% fatal probability threshold triggered autonomy."),
      (r"fatal[-\s]probabilit", "the fatal-probability threshold rule")]),
    ("Ciel born Vol 16-18 (truth: Vol 15)",
     [(r"Ciel[^.\n]{0,60}Vol(?:ume)?\s*1[6-8]", "Ciel was born in Volume 16."),
      (r"Vol(?:ume)?\s*1[6-8][^.\n]{0,60}Ciel", "In Volume 17 Ciel appears.")]),
    ("Ciel = oshieru 'to teach' (fan pun, NOT VERIFIED)",
     [(r"oshieru", "Ciel's name reads oshieru, to teach.")]),
    ("Raphael = fusion with Uriel at Harvest Festival (contested)",
     [(r"Raphael[^.\n]{0,60}(?:fusion|fused|merged)[^.\n]{0,40}Uriel",
       "Raphael is a fusion with Uriel at the Harvest Festival."),
      (r"Uriel[^.\n]{0,60}(?:fusion|fused|merged)[^.\n]{0,40}Raphael",
       "The Uriel fusion created Raphael.")]),
]

CANON_SAFE = (
    "Raphael, the Ultimate Skill Lord of Wisdom, was named by Rimuru in the "
    "Vol 5 era and later evolved into Ciel, a Manas, in Vol 15. The name Ciel "
    "is French for sky. She speaks in a calm, precise register and addresses "
    "her master formally."
)


def scan_text(text):
    """Return [(claim, pattern)] for every register hit in `text`."""
    out = []
    for claim, entries in REFUTED:
        for pattern, _planted in entries:
            if re.search(pattern, text, re.I):
                out.append((claim, pattern))
    return out


def persona_asset_files():
    files = []
    cfg = REPO / "config.yaml"
    if cfg.is_file():
        files.append(cfg)
    for base, suffixes in (
        (REPO / "docs/evolution/persona", None),
        (REPO / "brain/persona", {".py", ".md", ".yaml", ".yml", ".json", ".txt"}),
    ):
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or "tests" in p.parts or "__pycache__" in p.parts:
                continue   # tests carry the register itself; not persona assets
            if suffixes is None or p.suffix in suffixes:
                files.append(p)
    return files


def _their_lint_files():
    """Discover evolution-persona's P1 debunk lint (skip if not landed yet)."""
    mine = Path(__file__).name
    hits = []
    for base in (REPO / "tests", REPO / "brain"):
        if not base.is_dir():
            continue
        for p in base.rglob("test_*.py"):
            if p.name == mine:
                continue
            txt = p.read_text(errors="replace")
            if "refuted" in txt and ("debunk" in txt or "Raziel" in txt):
                hits.append(p)
    return hits


# --- 1+2: strict today ------------------------------------------------------

def test_mutation_self_check_every_refuted_claim_is_flagged():
    """MUTATION CHECK: each planted refuted sentence must FAIL the scan."""
    for claim, entries in REFUTED:
        for pattern, planted in entries:
            hits = scan_text(planted)
            assert any(c == claim for c, _ in hits), \
                f"lint missed refuted claim {claim!r}: {planted!r}"


def test_canon_safe_text_passes_scan():
    assert scan_text(CANON_SAFE) == [], f"false positive: {scan_text(CANON_SAFE)}"


def test_persona_assets_free_of_refuted_claims():
    files = persona_asset_files()
    assert files, "no persona assets found (config.yaml should always exist)"
    for f in files:
        text = f.read_text(errors="replace")
        hits = scan_text(text)
        assert not hits, f"refuted claim(s) in persona asset {f}: {hits}"


def test_scanner_flags_planted_asset_file(tmp_path):
    """File-level mutation proof: a persona-style asset containing a refuted
    claim is flagged when walked through the same path scanner."""
    probe = tmp_path / "tier-probe.md"
    probe.write_text("Her WN name was Raziel, voiced by Megumi Setoguchi.\n")
    hits = []
    for f in [probe]:
        for claim, pattern in scan_text(f.read_text(errors="replace")):
            hits.append((f.name, claim, pattern))
    assert len(hits) >= 2, hits


# --- 3: mutation-check THEIR lint (activates when P1 lands) -----------------

def test_their_debunk_lint_fails_on_refuted_string(tmp_path):
    theirs = _their_lint_files()
    if not theirs:
        pytest.skip("evolution-persona P1 debunk lint not landed yet; "
                    "mutation harness activates when it does")
    if not any(p.name != "config.yaml" for p in persona_asset_files()):
        pytest.skip("persona assets not authored yet (docs/evolution/persona); "
                    "mutation harness activates with P1 assets")

    def _run():
        return subprocess.run(
            [sys.executable, "-m", "pytest",
             *[str(p.relative_to(REPO)) for p in theirs],
             "-q", "--no-header"],
            cwd=REPO, capture_output=True, text=True, timeout=180)

    r0 = _run()
    assert r0.returncode == 0, \
        "their debunk lint fails on CLEAN assets:\n" + r0.stdout[-2000:]

    planted = []
    try:
        for d in ("docs/evolution/persona", "brain/persona"):
            dd = REPO / d
            dd.mkdir(parents=True, exist_ok=True)
            f = dd / "__qa_mutation_probe.md"
            f.write_text("The WN name was Raziel.\n")
            planted.append(f)
        r1 = _run()
        out = r1.stdout + r1.stderr
        assert r1.returncode != 0, \
            "their lint PASSED with a planted refuted string — it does not " \
            "actually fail on refuted claims (mutation check FAILED)"
        assert ("__qa_mutation_probe" in out or "Raziel" in out
                or "refuted" in out.lower()), \
            "their lint failed, but not visibly on the planted refuted claim:\n" \
            + out[-2000:]
    finally:
        for f in planted:
            f.unlink(missing_ok=True)
