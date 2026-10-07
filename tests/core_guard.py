#!/usr/bin/env python3
"""Core Guard manifest tool (AGENT_RULES §8).

  python tests/core_guard.py            verify (exit 1 on drift)
  python tests/core_guard.py --update   rewrite the manifest

--update is ONLY legitimate with an integrator-approved request in
docs/requests/ — mention it:  --update --approval docs/requests/<file>.md
"""
import hashlib
import json
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


def main(argv):
    if '--update' in argv:
        approval = None
        if '--approval' in argv:
            approval = argv[argv.index('--approval') + 1]
            if not (REPO / approval).exists():
                print(f'approval file not found: {approval}')
                return 2
        MANIFEST.write_text(json.dumps(hashes(), indent=2, sort_keys=True)
                            + '\n')
        note = f' (approval: {approval})' if approval else \
            ' !! NO APPROVAL REFERENCE — integrator review expected !!'
        print(f'manifest updated{note}')
        return 0
    current = hashes()
    stored = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
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
