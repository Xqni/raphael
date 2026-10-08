"""Control-plane consistency: the coordinator's DRY-RUN handler
(tools/conductor/handler_dryrun.py — parses OWNERSHIP.md itself to veto
lane diffs) must agree with qa-security's merge-loop checker
(tests/ownership_check.py). Divergent parsers = the handler approving a
merge the checker vetoes (or drowning lanes in false vetoes).

Both parse the SAME source of truth (docs/OWNERSHIP.md lane table).
"""
import pytest
from ownership_check import check_file, load_lane_table

try:
    from tools.conductor import handler_dryrun as HD
except Exception as e:  # noqa: BLE001 — import structure must be explicit
    HD = None
    _import_error = e

pytestmark = []  # module kept pytest-free otherwise


def _require_hd():
    assert HD is not None, f'cannot import handler_dryrun: {_import_error}'


def _ownership_text():
    from pathlib import Path
    return Path('docs/OWNERSHIP.md').read_text(encoding='utf-8')


def test_dryrun_parser_sees_the_same_lanes():
    _require_hd()
    theirs = HD.parse_ownership(_ownership_text())
    mine = load_lane_table()
    assert set(theirs) == set(mine), (
        f'lane-set drift: dry-run-only={sorted(set(theirs) - set(mine))} '
        f'checker-only={sorted(set(mine) - set(theirs))}')


def test_dryrun_and_checker_agree_on_owner_samples():
    """Sample paths across every lane: the owner BOTH tools compute must be
    the same (multi-owner advisory matches are allowed if my lane is in it)."""
    _require_hd()
    theirs_map = HD.parse_ownership(_ownership_text())
    samples = [
        ('tests/contract/test_auth.py', 'qa-security'),
        ('.github/workflows/ci.yml', 'qa-security'),
        ('docs/reviews/x.md', 'qa-security'),
        ('brain/loop.py', 'brain-core'),
        ('brain/tests/test_ws.py', 'brain-core'),
        ('brain/router/core.py', 'router'),
        ('brain/voice/tts.py', 'voice'),
        ('body/win/audio_in.py', 'voice'),
        ('body/win/main.py', 'pc-control'),
        ('body/orb/src/main.js', 'orb'),
        ('supervisor/main.py', 'infra'),
        ('tools/conductor/coord.py', 'integrator'),
        ('docs/PROTOCOL.md', 'integrator'),
    ]
    for path, expected in samples:
        dry_owners = HD.owners_of(path, theirs_map)
        assert expected in dry_owners, \
            f'dry-run owners_of({path}) = {dry_owners}, expected {expected}'
        # my checker: the expected owner must be allowed to edit it
        assert check_file(path, expected, load_lane_table()) is None, \
            f'my checker vetoes {expected} on its own file {path}'


@pytest.mark.xfail(
    strict=False,
    reason='CONFIRMED 2026-10-08: handler_dryrun.ownership_check vetoes a '
           "lane's OWN docs/lanes/<lane>.md + docs/status/<lane>.md — the "
           'OWNERSHIP.md prose carve-out ("plus its docs/lanes/... + '
           'docs/status/...") is not machine-readable in the table-only '
           'parser (my checker has explicit carve-outs). Live proof: veto='
           "['docs/lanes/qa-security.md (owned by: nobody/unlisted=integrator)',"
           " 'docs/status/qa-security.md ...'] — request: qa-security -> "
           'integrator handler-dryrun-lane-doc-carveout')
def test_dryrun_veto_is_clean_for_this_lane():
    """Live read-only check: the handler's veto pass over MY branch's diff
    must come back empty (same conclusion as my own ownership --diff)."""
    _require_hd()
    from pathlib import Path
    theirs_map = HD.parse_ownership(_ownership_text())
    veto, advisory, note = HD.ownership_check(
        'qa-security', Path.cwd(), theirs_map, base='origin/main')
    assert veto == [], f'dry-run veto vs my own diff: {veto} ({note})'
