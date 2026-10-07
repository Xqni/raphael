"""Wave-5 gate tests: Analysis/Simulation privacy tripwires.

Neither feature exists yet (WAVES.md Wave 5 lists them; no impl, no spec
frames in §3). Contract-first rule ([21]: new frames/contracts = integrator
request FIRST) → request filed
`qa-security__to__integrator__analysis-simulation-privacy-contract.md`.
These tripwires define the invariants the implementation must satisfy and
go GREEN when it lands correctly; they FAIL LOUDLY if it lands ungated
(no xfail masking).

Invariants pinned here (same class as PROTOCOL §7/§11):
- private mode suppresses ALL model calls in the feature path;
- findings/simulation output passes redaction before speech/journal/prompt;
- untrusted wrapping (AGENTS §9) for any external data the feature ingests.
"""
import re
from pathlib import Path

FEATURE_NAME_RE = re.compile(r'(analysis|simulation)', re.I)
PRIVATE_RE = re.compile(r'(mode\.private|set_private_mode|check_private)', re.I)
REDACT_RE = re.compile(r'redact', re.I)
UNTRUSTED_RE = re.compile(r'(as_untrusted|untrusted)', re.I)

# production feature sources (tests + docs excluded)
def _feature_sources() -> list:
    hits = []
    for root in (Path('brain'), Path('body')):
        if not root.exists():
            continue
        for p in root.rglob('*.py'):
            if 'venv' in p.parts or '__pycache__' in p.parts:
                continue
            if 'tests' in p.parts or p.name.startswith('test_'):
                continue
            if FEATURE_NAME_RE.search(p.name):
                hits.append(p)
    return hits


def test_analysis_simulation_privacy_gates_present():
    srcs = _feature_sources()
    if not srcs:
        import pytest as _pytest
        _pytest.skip('Analysis/Simulation not implemented yet — tripwire '
                     'armed, request filed (contract-first)')
    blob = '\n'.join(p.read_text(encoding='utf-8') for p in srcs)
    missing = []
    if not PRIVATE_RE.search(blob):
        missing.append('private-mode gate (ALL model calls suppressed)')
    if not REDACT_RE.search(blob):
        missing.append('privacy.redact on spoken/journaled/prompted output')
    if not UNTRUSTED_RE.search(blob):
        missing.append('untrusted wrapping of external data (AGENTS §9)')
    assert not missing, (
        f'Analysis/Simulation landed WITHOUT privacy gates: {missing} '
        f'(sources: {[str(p) for p in srcs]})')


def test_analysis_simulation_frames_must_be_protocol_documented():
    """If/when the features emit frames, the conformance emitter scan +
    §3 whitelist cover them — this test just pins that the scanner still
    sees production emissions (so a silent scan break cannot hide a new
    undocumented frame)."""
    from conformance.test_protocol import _production_emitted_types
    emitted = _production_emitted_types()
    assert emitted, 'production frame scan is empty — scanner broken?'
    # answer/report frames, once implemented, MUST appear in §3 first:
    from conformance.test_protocol import (_protocol_brain_to_client_types,
                                           _protocol_client_to_brain_types)
    documented = (_protocol_brain_to_client_types()
                  | _protocol_client_to_brain_types() | {'ping'})
    for t, src in emitted.items():
        assert t in documented, f'{t} emitted from {sorted(src)} but not in §3'
