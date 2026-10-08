"""Wave 5H QA-1 wiring guards: the CI scanners + their configs must stay
present and parseable — so a drive-by edit can't silently drop a gate.

(Spinach test for .github/workflows/ci.yml, .gitleaks.toml,
.github/dependabot.yml, tests/security/{bandit.yaml,gitleaks-baseline.json,
SCANNERS.md}.)
"""
import json
import tomllib
from pathlib import Path

import yaml

REPO = Path.cwd()


def _ci():
    return yaml.safe_load((REPO / '.github' / 'workflows' / 'ci.yml')
                          .read_text(encoding='utf-8'))


def test_ci_has_security_scanners_job_with_all_four_scanners():
    wf = _ci()
    job = wf['jobs'].get('security-scanners')
    assert job is not None, 'security-scanners job removed from ci.yml'
    blob = json.dumps(job)
    for needle in ('--baseline-path', 'gitleaks.tgz', 'pip-audit', 'bandit',
                   'npm audit --audit-level=critical',
                   'scripts/secret-scan.sh'):   # infra engine (their ask)
        assert needle in blob, f'scanner step missing from job: {needle}'
    # history scan needs full checkout
    checkout = next(s for s in job['steps']
                    if str(s.get('uses', '')).startswith('actions/checkout'))
    assert checkout.get('with', {}).get('fetch-depth') == 0


def test_existing_os_jobs_still_present():
    """QA-1: both OS jobs must stay green — they must still EXIST."""
    jobs = _ci()['jobs']
    assert 'conformance' in jobs          # ubuntu+windows matrix
    assert 'brain-and-mocks' in jobs      # ubuntu
    assert 'body-unit-windows' in jobs    # windows
    matrix = jobs['conformance']['strategy']['matrix']['os']
    assert set(matrix) == {'ubuntu-latest', 'windows-latest'}


def test_ci_least_privilege_aud20():
    """AUD-20 addendum: workflow-level minimal permissions + no persisted
    checkout credentials anywhere."""
    wf = _ci()
    assert wf.get('permissions') == {'contents': 'read'}, wf.get('permissions')
    checkouts = [st for job in wf['jobs'].values() for st in job['steps']
                 if str(st.get('uses', '')).startswith('actions/checkout')]
    assert checkouts, 'no checkout steps found'
    for st in checkouts:
        assert st.get('with', {}).get('persist-credentials') is False, st


def test_ownership_step_uses_merge_base_for_branches():
    """CI improvement [40]: branch/PR runs must diff against the merge-base
    with origin/main (lane's OWN diff), not event.before — ff-merging main
    used to drag other lanes' commits into the range (orb's false-violation
    diagnosis, integrator-confirmed)."""
    src = Path('.github/workflows/ci.yml').read_text(encoding='utf-8')
    assert 'git merge-base HEAD origin/main' in src, \
        'ownership step lost the merge-base base derivation'
    assert 'if [ "$REF" != "main" ]' in src


def test_gitleaks_config_and_baseline_parse():
    cfg = tomllib.loads((REPO / '.gitleaks.toml').read_text(encoding='utf-8'))
    rule_ids = {r['id'] for r in cfg['rules']}
    assert {'local-username-dami', 'local-home-drive-path',
            'local-private-ip'} <= rule_ids, rule_ids
    assert cfg['extend']['useDefault'] is True, 'default secret rules dropped'
    baseline = json.loads(
        (REPO / 'tests' / 'security' / 'gitleaks-baseline.json')
        .read_text(encoding='utf-8'))
    assert isinstance(baseline, list) and baseline, 'baseline empty'
    assert all('Fingerprint' in f for f in baseline)
    # baseline must be UNREDACTED (redacted baselines suppress nothing —
    # verified live 2026-10-08; see tests/security/SCANNERS.md)
    assert any(f.get('Match') and f['Match'] != 'REDACTED' for f in baseline)


def test_bandit_config_has_documented_skips_and_excludes():
    cfg = yaml.safe_load((REPO / 'tests' / 'security' / 'bandit.yaml')
                         .read_text(encoding='utf-8'))
    assert set(cfg['skips']) == {'B602', 'B324'}, cfg['skips']
    assert '.venv' in cfg['exclude_dir']
    # written reasons live next to the config
    scanners = (REPO / 'tests' / 'security' / 'SCANNERS.md').read_text(
        encoding='utf-8')
    for needle in ('B602', 'B324', 'baseline', 'npm audit', 'electron'):
        assert needle in scanners, f'SCANNERS.md missing rationale: {needle}'


def test_dependabot_covers_the_three_manifests():
    db = yaml.safe_load((REPO / '.github' / 'dependabot.yml')
                        .read_text(encoding='utf-8'))
    assert db['version'] == 2
    pairs = {(u['package-ecosystem'], u['directory']) for u in db['updates']}
    assert ('pip', '/tests') in pairs
    assert ('npm', '/body/orb') in pairs
    assert ('github-actions', '/') in pairs
