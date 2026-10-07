#!/usr/bin/env python3
"""Core Guard manifest tool (AGENT_RULES §8).

  python tests/core_guard.py            verify (exit 1 on drift)
  python tests/core_guard.py --update   rewrite the manifest

--update is ONLY legitimate with an integrator-approved request in
docs/requests/ — mention it:  --update --approval docs/requests/<file>.md
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / 'tests' / 'core_guard_manifest.json'

CORE_GUARD_FILES = [
    'brain/confirm.py',
    'brain/auth.py',
    'brain/control.py',
    'brain/mode.py',
]


def hashes() -> dict:
    out = {}
    for rel in CORE_GUARD_FILES:
        out[rel] = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
    return out


def _approval_located(rel: str) -> str | None:
    """Approval files may still live on a lane branch pre-merge (requests
    travel with the requester's branch). Returns where it was found."""
    if (REPO / rel).exists():
        return 'worktree'
    try:
        out = subprocess.run(
            ['git', 'log', '--all', '--format=%H', '--', rel],
            cwd=REPO, capture_output=True, text=True, timeout=20)
        if out.returncode == 0 and out.stdout.strip():
            first = out.stdout.splitlines()[0]
            where = subprocess.run(
                ['git', 'name-rev', '--name-only', first],
                cwd=REPO, capture_output=True, text=True, timeout=20)
            return f'git:{where.stdout.strip() or first[:10]}'
    except Exception:  # noqa: BLE001
        pass
    return None


def main(argv):
    if '--update' in argv:
        approvals = []
        if '--approval' in argv:
            idxs = [i for i, a in enumerate(argv) if a == '--approval']
            for i in idxs:
                rel = argv[i + 1]
                found = _approval_located(rel)
                if not found:
                    print(f'approval file not found anywhere: {rel}')
                    return 2
                approvals.append(f'{rel} [{found}]')
        note = (' (approval: ' + '; '.join(approvals) + ')') if approvals else \
            ' !! NO APPROVAL REFERENCE — integrator review expected !!'
        MANIFEST.write_text(json.dumps(hashes(), indent=2, sort_keys=True)
                            + '\n', encoding='utf-8')
        print(f'manifest updated{note}')
        return 0
    current = hashes()
    stored = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {}
    drift = {k: (stored.get(k), v) for k, v in current.items()
             if stored.get(k) != v}
    if drift:
        print('CORE GUARD DRIFT (AGENT_RULES §8 — needs integrator approval):')
        for k, (exp, got) in drift.items():
            print(f'  {k}: expected {exp}, got {got}')
        return 1
    print(f'Core Guard OK ({len(current)} files byte-stable)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
