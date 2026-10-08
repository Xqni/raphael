"""Wave-5 evolution gate tests (qa-security angle): the self-evolution
CONTROLS themselves are pinned here — Core Guard integrity (tamper + boot
refusal), rollback drill behavior, probation triggers, and the cross-source
consistency between zones.CORE and the Core Guard manifest.

Evolution-persona owns brain/evolution + brain/persona and has its own
unit suites; these are the ROOT-level gate assertions (fail-closed paths,
negative/tamper drills, list cross-checks) that must hold no matter how the
internals evolve.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path.cwd()
MANIFEST = REPO / 'tests' / 'core_guard_manifest.json'


# ---- 1. Core Guard integrity ----------------------------------------------
def test_verify_detects_tampered_manifest():
    """Negative drill: a corrupted manifest hash must fail `core_guard.py`
    (exit != 0 with DRIFT output) — the tool is the single source of truth
    that brain.evolution.rollback.verify_core_guard delegates to."""
    original = MANIFEST.read_text(encoding='utf-8')
    try:
        doc = json.loads(original)
        first = sorted(doc)[0]
        doc[first] = 'f' * 64
        MANIFEST.write_text(json.dumps(doc, indent=2, sort_keys=True),
                            encoding='utf-8')
        r = subprocess.run([sys.executable, str(REPO / 'tests' / 'core_guard.py')],
                           capture_output=True, text=True, cwd=REPO)
        assert r.returncode != 0, 'verify passed with a corrupted manifest'
        assert 'DRIFT' in (r.stdout + r.stderr), r.stdout + r.stderr
    finally:
        MANIFEST.write_text(original, encoding='utf-8')
    # restore leaves a green verify (no lingering damage)
    r = subprocess.run([sys.executable, str(REPO / 'tests' / 'core_guard.py')],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout


def test_boot_refuses_to_serve_on_manifest_drift():
    """Live-proven mechanism (2026-10-08, my own un-repinned workflow edit):
    the lifespan verify must RAISE before the brain serves anything."""
    from fastapi.testclient import TestClient
    from brain import coreguard
    original = MANIFEST.read_text(encoding='utf-8')
    try:
        doc = json.loads(original)
        first = sorted(doc)[0]
        doc[first] = '0' * 64
        MANIFEST.write_text(json.dumps(doc, indent=2, sort_keys=True),
                            encoding='utf-8')
        from brain.app import app
        with pytest.raises(RuntimeError, match='REFUSING TO SERVE'):
            with TestClient(app):
                pass
        # the refusal must have armed SAFE_MODE (drift => block dispatch)
        assert coreguard.SAFE_MODE.get('active') is True, coreguard.SAFE_MODE
    finally:
        MANIFEST.write_text(original, encoding='utf-8')
        # ...and MUST disarm it: SAFE_MODE is process-global and blocks the
        # act pipeline for every LATER test in this session (live-caused
        # 9-test act/confirm timeout cascade before this cleanup existed)
        coreguard.SAFE_MODE = {'active': False}
        coreguard._boot_result = None
        coreguard._last_verify = 0.0


def test_rollback_verify_delegates_and_fails_closed():
    """brain.evolution.rollback must fail closed when the guard tool or
    manifest is absent (design 01 §6 rule 10) and pass on the real repo."""
    from brain.evolution import rollback as R
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        ok, reason = R.verify_core_guard(repo=Path(td))
        assert ok is False, reason          # no tool inside a bare repo
    ok, reason = R.verify_core_guard()
    assert ok is True, reason


# ---- 2. rollback drills ---------------------------------------------------
def test_rollback_commands_generate_but_never_execute(tmp_path):
    """rollback/retag only GENERATE command strings; calling them must never
    move a repo's HEAD (execution is infra's out-of-band path, by design)."""
    from brain.evolution import rollback as R
    def git(*args):
        return subprocess.run(['git', *args], cwd=tmp_path,
                              capture_output=True, text=True, check=True)
    git('init', '-q')
    git('config', 'user.email', 't@t')
    git('config', 'user.name', 't')
    (tmp_path / 'a.txt').write_text('v1', encoding='utf-8')
    git('add', '.')
    git('commit', '-qm', 'v1')
    before = git('rev-parse', 'HEAD').stdout.strip()
    (tmp_path / 'a.txt').write_text('v2', encoding='utf-8')
    git('add', '.')
    git('commit', '-qm', 'v2')
    cmd_rollback = R.rollback_command('HEAD~1')
    cmd_retag = R.retag_command('HEAD')
    after = git('rev-parse', 'HEAD').stdout.strip()
    assert after != before, 'fixture commit did not advance HEAD'
    assert 'git' in cmd_rollback and 'HEAD~1' in cmd_rollback, cmd_rollback
    assert 'git' in cmd_retag and 'HEAD' in cmd_retag, cmd_retag
    # generation only: HEAD untouched by calling the generators
    assert git('rev-parse', 'HEAD').stdout.strip() == after


# ---- 3. baseline promote gate (fail-closed) -------------------------------
def test_baseline_compare_fails_closed():
    from brain.evolution import baseline as B

    good = {'commit': 'a' * 40, 'core_guard': {'ok': True},
            'shadow': {'ok': True, 'rc': 0},
            'transcripts': [{'name': 't', 'steps': [
        {'type': 'act', 'name': 'screenshot', 'target': 'screen'}]}]}
    # no baseline at all -> refuse
    assert B.compare(dict(good), None)['ok'] is False
    # core guard flipped in candidate -> refuse
    bad = dict(good); bad['core_guard'] = {'ok': False}
    assert B.compare(bad, good)['ok'] is False
    # core guard was bad in the BASELINE (poisoned baseline) -> refuse
    bad_base = dict(good); bad_base['core_guard'] = {'ok': False}
    assert B.compare(good, bad_base)['ok'] is False
    # shadow run failed -> refuse
    bad_shadow = dict(good); bad_shadow['shadow'] = {'ok': False, 'rc': 7}
    assert B.compare(bad_shadow, good)['ok'] is False
    # transcript drift -> refuse
    drifted = {'commit': 'b' * 40, 'core_guard': {'ok': True},
               'shadow': {'ok': True, 'rc': 0},
               'transcripts': [{'name': 't', 'steps': [
        {'type': 'act', 'name': 'uia', 'target': 'screen'}]}]}
    verdict = B.compare(drifted, good)
    assert verdict['ok'] is False and verdict['deltas']
    # identical candidate (commit moved alone is allowed) -> pass
    clean = dict(good); clean['commit'] = 'b' * 40
    assert B.compare(clean, good)['ok'] is True


# ---- 4. zones x Core Guard cross-source consistency -----------------------
def test_zones_classify_every_core_guard_entry_as_core():
    """The two guard LISTS must agree: every manifest key must land in
    Zone.CORE (paths evolution may never auto-promote), else a file could be
    guarded by qa's manifest yet promotable by evolution's classifier."""
    from brain.evolution import zones as Z
    doc = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert doc, 'manifest empty'
    for key in doc:
        probe = key[:-3] + 'probe.py' if key.endswith('/**') else key
        assert Z.zone(probe) is Z.Zone.CORE, (
            f'{key} (probe {probe}) classifies as '
            f'{Z.zone(probe).value} — manifest/zones drift')


def test_zones_fail_closed_and_authority_content_reguards():
    from brain.evolution import zones as Z
    # unknown path -> CORE (never auto-promoted)
    assert Z.zone('some/new/thing.py') is Z.Zone.CORE
    assert Z.classify([]) is Z.Zone.CORE
    # authority-bearing content re-guards even a mutable-looking path
    diff = (
        "--- a/config.d/qa-security.yaml\n"
        "+++ b/config.d/qa-security.yaml\n"
        "+safety:\n"
        "+  confirm_actions: []\n"
    )
    assert Z.zone('config.d/qa-security.yaml', diff) is Z.Zone.CORE
    assert Z.classify(['config.d/qa-security.yaml'],
                      diff) is Z.Zone.CORE
    assert Z.is_auto_promotable(['config.d/qa-security.yaml'], diff) is False
    # plain mutable path with clean diff is promotable (the intended path)
    assert Z.classify(['skills/foo/SKILL.md']) is Z.Zone.MUTABLE


# ---- 5. probation triggers ------------------------------------------------
def test_probation_triggers_fail_closed(tmp_path):
    from brain.persona import probation as P
    state_file = tmp_path / 'probation.json'

    # only an UNLOCK (lower -> higher) opens a window
    st = P.start('great_sage', 'raphael', {'jobs': 3, 'hours': 1},
                 path=state_file)
    assert st['status'] == 'active'
    with pytest.raises(ValueError):
        P.start('raphael', 'great_sage', {'jobs': 3, 'hours': 1},
                path=state_file)          # downward = rollback, not probation
    with pytest.raises(ValueError):
        P.start('great_sage', 'no_such_tier', {'jobs': 3, 'hours': 1},
                path=state_file)

    # a FATAL event fails the window now, sticky: later clean records cannot
    # resurrect it (design 05 §3.2)
    st = P.record(st, ok=True, path=state_file)
    st = P.record(st, ok=False, fatal=True, reason='severity-1',
                  path=state_file)
    st = P.record(st, ok=True, path=state_file)
    assert st['status'] == 'failed'
    verdict = P.evaluate(st, path=state_file)
    assert verdict['status'] == 'failed', verdict

    # expiry without enough evidence fails (autonomy re-earned, not kept)
    st2 = P.start('great_sage', 'raphael', {'jobs': 50, 'hours': 24},
                  path=state_file, now_ms=0)
    st2 = P.record(st2, ok=True, now_ms=1000, path=state_file)
    far_future_ms = 0 + 48 * 3_600_000       # 48h later, 1 of 50 jobs
    verdict = P.evaluate(st2, now_ms=far_future_ms, path=state_file)
    assert verdict['status'] == 'failed', verdict

    # demotion only ever lowers
    assert P.demotion_target('raphael') == 'great_sage'
    assert P.demotion_target('ciel') == 'raphael'
    assert P.demotion_target('great_sage') == 'great_sage'


def test_probation_state_lives_outside_the_git_tree():
    """Probation state = runtime data (design 05): instance data-dir, never
    a tracked file."""
    from brain.persona import probation as P
    state_path = P.state_path()
    assert not str(state_path).startswith(str(REPO)), state_path
    r = subprocess.run(['git', 'ls-files', '--', str(state_path)],
                       cwd=REPO, capture_output=True, text=True)
    assert r.stdout.strip() == '', f'probation state tracked: {r.stdout}'
