#!/usr/bin/env python3
"""Lane ownership checker (docs/OWNERSHIP.md) — the integrator runs this in
the merge loop; qa-security owns the tool.

Usage:
  python tests/ownership_check.py --lane <lane> --files <f> [<f> ...]
  python tests/ownership_check.py --lane <lane> --diff [--base main]
  python tests/ownership_check.py --lane <lane> --worktree
  python tests/ownership_check.py --lane <lane> --diff --format json

Exit codes: 0 = clean, 1 = ownership violations, 2 = usage error.

Rules (OWNERSHIP.md):
- a lane may only create/edit files under its own paths (lane table);
- plus its own docs/lanes/<lane>.md and docs/status/<lane>.md;
- docs/requests/** is writable by every lane (AGENT_RULES §2);
- config.d/<lane>.yaml belongs to that lane (INTERFACES §c);
- anything UNLISTED is the integrator's — only the integrator may change it.
"""
import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OWNERSHIP = REPO / 'docs' / 'OWNERSHIP.md'


def _expand_braces(pattern: str) -> list:
    """Expand {a,b,c} groups (recursive)."""
    m = re.search(r'\{([^{}]*)\}', pattern)
    if not m:
        return [pattern]
    out = []
    for alt in m.group(1).split(','):
        expanded = pattern[:m.start()] + alt.strip() + pattern[m.end():]
        out.extend(_expand_braces(expanded))
    return out


def _variants(pat: str) -> list:
    """`assets/x.wav/.txt` style shorthands -> both real paths."""
    out = [pat]
    if '/.' in pat:
        base, ext2 = pat.split('/.', 1)
        out.append(base)
        root = base.rsplit('.', 1)[0] if '.' in base else base
        out.append(root + '.' + ext2)
    return out


def load_lane_table(path: Path = OWNERSHIP) -> dict:
    """-> {lane: [pattern, ...]} from the OWNERSHIP.md lane table."""
    lanes = {}
    for line in path.read_text().splitlines():
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) < 2:
            continue
        lane_m = re.match(r'\*\*([a-z0-9-]+)\*\*', cells[0])
        if not lane_m:
            continue
        lane = lane_m.group(1)
        pats = []
        for seg in re.findall(r'`([^`]+)`', cells[1]):
            seg = seg.strip()
            if not seg:
                continue
            for part in _expand_braces(seg):
                # split prose commas only after brace expansion
                for sub in (part.split(',') if '{' not in part else [part]):
                    sub = sub.strip()
                    if sub:
                        pats.extend(_variants(sub))
        lanes[lane] = sorted(dict.fromkeys(pats))
    return lanes


def _owner_of(rel: str, lanes: dict) -> tuple:
    """-> (owner, matched): longest matching pattern wins (dir patterns get
    a `/**` candidate); unmatched -> ('integrator', False)."""
    rel = rel[2:] if rel.startswith('./') else rel
    best, best_len, matched = 'integrator', -1, False
    for lane, pats in lanes.items():
        for pat in pats:
            candidates = [pat]
            if not pat.endswith('**'):
                candidates.append(pat.rstrip('/') + '/**')
            for cand in candidates:
                if fnmatch.fnmatch(rel, cand) and len(cand) > best_len:
                    best, best_len, matched = lane, len(cand), True
    return best, matched


def check_file(rel: str, lane: str, lanes: dict) -> str | None:
    """-> violation reason or None if allowed."""
    rel = rel[2:] if rel.startswith('./') else rel
    # universal write allowances
    if rel.startswith('docs/requests/'):
        return None
    if rel in (f'docs/lanes/{lane}.md', f'docs/status/{lane}.md'):
        return None
    if rel == f'config.d/{lane}.yaml':
        return None
    # another lane's config fragment is never writable
    m = re.match(r'config\.d/([a-z0-9-]+)\.yaml$', rel)
    if m and m.group(1) != lane:
        return f"config fragment belongs to lane '{m.group(1)}'"
    if lane == 'integrator':
        return None                      # integrator owns all merges
    owner, matched = _owner_of(rel, lanes)
    if not matched:
        return 'unlisted path — integrator-owned by default'
    if owner != lane:
        return f"owned by lane '{owner}'"
    return None


def git_files(base: str, worktree: bool) -> list:
    files = []
    diff = subprocess.run(
        ['git', 'diff', '--name-only', '--diff-filter=ACMR',
         f'{base}...HEAD'], cwd=REPO, capture_output=True, text=True)
    if diff.returncode == 0:
        files += [f for f in diff.stdout.splitlines() if f]
    if worktree:
        st = subprocess.run(['git', 'status', '--porcelain'], cwd=REPO,
                            capture_output=True, text=True)
        for line in st.stdout.splitlines():
            f = line[3:].strip()
            if ' -> ' in f:
                f = f.split(' -> ')[-1]
            if f and not f.endswith('/'):
                files.append(f)
    seen, out = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--lane', required=True)
    ap.add_argument('--files', nargs='*')
    ap.add_argument('--diff', action='store_true')
    ap.add_argument('--base', default='main')
    ap.add_argument('--worktree', action='store_true')
    ap.add_argument('--format', choices=('text', 'json'), default='text')
    args = ap.parse_args(argv)

    if args.files is not None:
        files = args.files
    elif args.diff or args.worktree:
        files = git_files(args.base, args.worktree)
    else:
        ap.error('need --files, --diff, or --worktree')
        return 2

    lanes = load_lane_table()
    if args.lane != 'integrator' and args.lane not in lanes:
        print(f'unknown lane: {args.lane} (known: {sorted(lanes)})')
        return 2

    violations = {}
    for f in files:
        reason = check_file(f, args.lane, lanes)
        if reason:
            violations[f] = reason

    if args.format == 'json':
        print(json.dumps(violations, indent=2, sort_keys=True))
    else:
        if violations:
            print(f'OWNERSHIP VIOLATIONS for lane {args.lane!r}:')
            for f, why in sorted(violations.items()):
                print(f'  {f}: {why}')
        else:
            print(f'ownership OK for lane {args.lane!r} '
                  f'({len(files)} file(s) checked)')
    return 1 if violations else 0


if __name__ == '__main__':
    sys.exit(main())
