"""SEC-7 CI side — workflow-level integrity invariants qa-security enforces
(the human still enables branch protection; ATTENTION posted 2026-10-08).

Invariants over EVERY file in .github/workflows/:
1. a minimal top-level `permissions:` block (contents:read — nothing else);
2. no `pull_request_target` trigger (PR-from-fork token escalation class);
3. every actions/checkout pins `persist-credentials: false`;
4. every external `uses:` is pinned to a full 40-hex commit SHA
   (mutable tags like @v4 are supply-chain-rot).
"""
import re
from pathlib import Path

import yaml

WF_DIR = Path('.github/workflows')
USES_RE = re.compile(r'^\s*-\s+uses:\s*(\S+)', re.M)
SHA_RE = re.compile(r'@[0-9a-f]{40}$')


def _workflows():
    files = sorted(WF_DIR.glob('*.yml')) + sorted(WF_DIR.glob('*.yaml'))
    assert files, 'no workflow files found'
    return files


def test_every_workflow_has_minimal_permissions():
    for f in _workflows():
        wf = yaml.safe_load(f.read_text(encoding='utf-8'))
        perms = wf.get('permissions')
        assert perms is not None, f'{f}: missing top-level permissions block'
        assert set(perms) <= {'contents'}, f'{f}: over-broad permissions {perms}'
        assert perms.get('contents') == 'read', f'{f}: contents must be read'


def test_no_pull_request_target_anywhere():
    for f in _workflows():
        src = f.read_text(encoding='utf-8')
        assert 'pull_request_target' not in src, \
            f'{f}: pull_request_target is forbidden (fork PR escalation)'


def test_every_checkout_never_persists_credentials():
    for f in _workflows():
        wf = yaml.safe_load(f.read_text(encoding='utf-8'))
        for job in wf.get('jobs', {}).values():
            for step in job.get('steps', []):
                if str(step.get('uses', '')).startswith('actions/checkout'):
                    assert step.get('with', {}).get('persist-credentials') \
                        is False, f'{f}: checkout without persist-credentials:false'


def test_every_external_action_is_sha_pinned():
    for f in _workflows():
        src = f.read_text(encoding='utf-8')
        for ref in USES_RE.findall(src):
            if ref.startswith('./'):
                continue                      # local composite actions OK
            assert SHA_RE.search(ref), (
                f'{f}: action not pinned to a commit SHA: {ref} '
                f'(mutable tag — resolve: gh api repos/<repo>/git/ref/tags/<tag>)')
