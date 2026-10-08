#!/usr/bin/env python3
"""SEC-1 value-blind personal-data scanner over git-tracked files.

Reports file:line + rule id ONLY — never the matched text (secret-shaped
data is especially never printed; AGENT_RULES §7). Exit: 0 = clean (or
advisory mode), 1 = findings in --strict mode, 2 = setup error.

Rules (tune in RULES below):
  FAIL-severity : local usernames, Windows drive paths, public IPs
  REVIEW        : private IP ranges, anime voice-clip names (may be
                  intentional references — human scrubs with context)

Usage:
  scripts/scan_personal.py               # full tracked scan, advisory (0)
  scripts/scan_personal.py --strict      # exit 1 if any non-allowlisted hit
  scripts/scan_personal.py --staged      # only git-staged files (pre-commit)
  scripts/scan_personal.sh [args]        # thin wrapper
"""
# ALLOWLIST POLICY (coordinator decision, coord ts 1791462190):
# exact paths ONLY — never a wildcard over tests/** or docs/**. Every entry
# carries a written reason; entries DIE when their reason does:
#   * scripts/{scan_personal.*, GIT-SCRUB-PLAN.md, SECRETS.md,
#     env.dev.template, install-env-dev.sh} — detection signatures /
#     scrub-plan / privacy docs CONTAIN the patterns by construction;
#   * supervisor/tests/test_audit_tooling.py — test fixtures plant the
#     patterns on purpose;
#   * tests/security/gitleaks-baseline.json — QA-1 transitional gitleaks
#     suppression LEDGER: its content is the already-known personal-data set
#     (locations are what a ledger is FOR; gitleaks compares real Match
#     values, so the ledger cannot be scrubbed to placeholders — verified
#     2026-10-08). It dies naturally at exit-criterion-4, when the
#     repo-wide scrub completes and BOTH scanners run empty; then this
#     line goes.
# The summary reports allowlist-skipped file counts so the human-facing
# exit-criteria count stays honest (scrub tracks the NON-ledger FAILs).

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _is_public_ipv4(matched: str) -> bool:
    """Filter for ip-public: real PUBLIC addresses only (loopback, RFC1918
    privates, link-local, multicast, 0.0.0.0 and version noise are other
    rules' business or not findings at all)."""
    parts = matched.split(".")
    if len(parts) != 4:
        return False
    try:
        octets = [int(p) for p in parts]
    except ValueError:
        return False
    if any(o > 255 for o in octets):
        return False
    a, b = octets[0], octets[1]
    if a in (0, 10, 127) or a >= 224:            # this-net/loopback/mcast+
        return False
    if a == 169 and b == 254:                    # link-local
        return False
    if a == 172 and 16 <= b <= 31:               # RFC1918 (REVIEW rule)
        return False
    if a == 192 and b == 168:                    # RFC1918 (REVIEW rule)
        return False
    if a == 100 and 64 <= b <= 127:              # CGNAT
        return False
    return True


# rule id -> (severity, compiled pattern, human label, match-filter|None)
RULES = [
    ("user-windows", "FAIL", re.compile(r"jxesu"),
     "Windows login name"),
    ("user-linux", "FAIL", re.compile(r"(?<![\w.-])dami(?![\w.-])"),
     "Linux username"),
    ("user-gh", "FAIL", re.compile(r"github\.com/Xqni"),
     "GitHub handle"),
    ("path-windows", "FAIL", re.compile(r"C:\\Users\\|/mnt/c/Users/"),
     "Windows user drive path"),
    ("path-home", "FAIL", re.compile(r"/home/dami(?![\w.-])"),
     "home directory path"),
    ("ip-public", "FAIL", re.compile(
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b(?![\d.])"),
     "public IPv4", _is_public_ipv4),
    ("ip-private", "REVIEW", re.compile(
        r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
     "private-range IP", None),
    ("voice-clip", "REVIEW", re.compile(
        r"raphael_reference_jp|\bslime\b", re.IGNORECASE),
     "anime voice-clip related name (Zira = MS product voice, excluded)", None),
    ("serial", "REVIEW", re.compile(
        r"\b(S/N|Serial(?:Number)?|SSN)[:= ]+[A-Za-z0-9-]{6,}\b"),
     "device serial", None),
]

# files that legitimately CONTAIN the patterns (the scanner itself, the
# scrub plan, and the privacy doc) — locations only, never content.
ALLOWLIST = re.compile(
    r"^scripts/scan_personal\.(py|sh)$|^scripts/GIT-SCRUB-PLAN\.md$"
    r"|^scripts/SECRETS\.md$|^scripts/env\.dev\.template$"
    r"|^scripts/install-env-dev\.sh$"
    # test files whose FIXTURES are deliberately the pattern strings
    r"|^supervisor/tests/test_audit_tooling\.py$"
    # QA-1 gitleaks baseline LEDGER (transitional; dies at exit-criterion-4
    # — see ALLOWLIST POLICY in the module header)
    r"|^tests/security/gitleaks-baseline\.json$")


def tracked_files(staged_only: bool) -> list[str] | None:
    """None = git itself failed (setup error); [] = nothing to scan."""
    cmd = ["git", "ls-files", "-z"]
    if staged_only:
        cmd = ["git", "diff", "--cached", "--name-only", "-z"]
    proc = subprocess.run(cmd, capture_output=True, cwd=ROOT)
    if proc.returncode != 0:
        return None
    return [f for f in proc.stdout.decode("utf-8", "replace").split("\0")
            if f]


def scan_file(rel: str) -> list[tuple[str, int]]:
    if ALLOWLIST.search(rel):
        return []
    path = ROOT / rel
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if "\0" in text:                       # binary
        return []
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for rule in RULES:
            rule_id, _sev, pat = rule[0], rule[1], rule[2]
            m = pat.search(line)
            if not m:
                continue
            if len(rule) > 4 and rule[4] is not None and not rule[4](m.group(0)):
                continue
            hits.append((rule_id, lineno))
    return hits


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    strict = "--strict" in argv
    staged = "--staged" in argv
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    files = tracked_files(staged)
    if files is None:
        print("[scan_personal] git command failed — not a git repo?")
        return 2
    if not files:
        scope = "staged" if staged else "tracked"
        print("[scan_personal] no %s files — nothing to scan" % scope)
        return 0
    findings: dict[str, list[tuple[str, int]]] = {}
    for rel in files:
        hits = scan_file(rel)
        if hits:
            findings[rel] = hits
    sev_of = {r[0]: r[1] for r in RULES}
    label_of = {r[0]: r[3] for r in RULES}
    total = sum(len(v) for v in findings.values())
    fail_total = sum(1 for v in findings.values()
                     for rid, _ in v if sev_of[rid] == "FAIL")
    allow_skipped = sum(1 for rel in files if ALLOWLIST.search(rel))
    for rel in sorted(findings):
        for rid, lineno in findings[rel]:
            print("[scan_personal] %-8s %s:%d  rule=%s (%s)"
                  % (sev_of[rid], rel, lineno, rid, label_of[rid]))
    scope = "staged" if staged else "tracked"
    print("[scan_personal] scanned %d %s files (%d allowlist-skipped), "
          "%d finding(s) (FAIL-severity: %d, non-ledger)"
          % (len(files), scope, allow_skipped, total, fail_total))
    if strict and total:
        print("[scan_personal] STRICT: findings present — scrub or "
              "coordinate (docs/scrub plan: scripts/GIT-SCRUB-PLAN.md)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
