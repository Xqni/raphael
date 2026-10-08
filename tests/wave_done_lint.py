#!/usr/bin/env python3
"""QA-4: machine-check for wave_done messages (packet docs/audit-tasks/
qa-security.md lines 7-8: a wave_done MUST link a green CI run — or, for
pure-local closures, a content hash of the test output — else it bounces).

  python tests/wave_done_lint.py              # lint the LAST wave_done in
                                              # ~/.raphael-coord/events/qa-security.jsonl
  python tests/wave_done_lint.py --msg "..."  # lint an arbitrary message
  python tests/wave_done_lint.py --file X     # lint events from another file

Accepts EITHER:
  - a GitHub Actions run reference: a full URL .../actions/runs/<id> or the
    bare token `run <id>` / `runs/<id>`  (preferred, QA-4 wording), or
  - a local test-output hash: `sha256:<64 hex>` (fallback for closures with
    no CI surface — must be the hash of the captured pytest output).
Exit 0 = present, exit 1 = bounce.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

RUN_URL = re.compile(r'https://github\.com/[^/\s]+/[^/\s]+/actions/runs/\d+')
RUN_ID = re.compile(r'\b(?:runs?/|run )(\d{6,})\b')
OUT_HASH = re.compile(r'\bsha256:([0-9a-f]{64})\b')


def validate(msg: str) -> tuple:
    if RUN_URL.search(msg):
        return True, 'ci-run-url'
    if RUN_ID.search(msg):
        return True, 'ci-run-id'
    if OUT_HASH.search(msg):
        return True, 'output-sha256'
    return False, 'MISSING: needs a green CI run id/URL or sha256:<64hex> of test output'


def last_wave_done(path: Path):
    if not path.exists():
        return None
    found = None
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get('type') == 'wave_done':
            found = m
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--msg')
    ap.add_argument('--file', default=os.path.expanduser(
        '~/.raphael-coord/events/qa-security.jsonl'))
    args = ap.parse_args(argv)
    if args.msg is not None:
        msg, src = args.msg, '<cli>'
    else:
        ev = last_wave_done(Path(args.file))
        if ev is None:
            print(f'no wave_done found in {args.file} — nothing to lint')
            return 1
        msg, src = str(ev.get('msg', '')), args.file
    ok, why = validate(msg)
    if ok:
        print(f'wave_done OK ({why}) — {src}')
        return 0
    print(f'wave_done BOUNCED ({why})')
    return 1


if __name__ == '__main__':
    sys.exit(main())
