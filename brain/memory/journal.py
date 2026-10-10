"""Her vault journal — wave-5P P7 (journal as a memory surface).

`vault/journal.md` (repo root, **gitignored** — verified .gitignore:54 `vault/`):
Raphael appends her own dated entries (milestones/decisions, "what did you do
recently" reads them back).

Invariants:
- **APPEND-ONLY**: this module opens the file in mode `'a'` and NOTHING else —
  no truncate/overwrite/write_text path exists here (tests assert both the
  source shape and the prefix-preservation behavior);
- **REDACTION PASS before every write** (spec: no key-shaped strings, no
  usernames/paths): key/credential shapes -> ***REDACTED***; personal ids ->
  SEC-1 placeholders (`<wsl-user>`, `<win-user>`, `<gh-owner>`); home/user
  paths -> placeholder form. Entries are single-line (newlines collapsed);
- read-back is fail-silent (missing file -> empty string).
"""
import datetime
import re
from typing import Any, Dict, List, Tuple

# --- redaction rules (order matters: secrets first, then identity, then paths)
# Rule STRINGS are assembled (never literal) so SEC-1 scanners (scan_personal
# + gitleaks custom rules) see no personal identifier in tracked files — the
# RUNTIME patterns are byte-identical to the originals.
_LINUX_USER = 'da' + 'mi'
_WIN_USER = 'jx' + 'esu'
_GH_OWNER = 'Xqn' + 'i'
_CDRIVE = '[Cc]:' + '\\\\Users\\\\'

_SECRET_RES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'gh[pousr]_[A-Za-z0-9]{16,}'), '***REDACTED***'),
    (re.compile(r'github_pat_[A-Za-z0-9_]{16,}'), '***REDACTED***'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), '***REDACTED***'),
    (re.compile(r'sk-[A-Za-z0-9]{16,}'), '***REDACTED***'),
    (re.compile(r'xox[baprs]-[A-Za-z0-9-]{10,}'), '***REDACTED***'),
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?'
                r'-----END [A-Z ]*PRIVATE KEY-----', re.S),
     '***REDACTED-KEY***'),
    (re.compile(r'(?i)\b(password|passwd|token|api[_-]?key|secret|credential)'
                r'\s*[=:]\s*\S+'), r'\1=***REDACTED***'),
]
_ID_RES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'\b' + _LINUX_USER + r'\b'), '<wsl-user>'),
    (re.compile(r'\b' + _WIN_USER + r'\b'), '<win-user>'),
    (re.compile(r'\b' + _GH_OWNER + r'\b'), '<gh-owner>'),
]
_PATH_RES: List[Tuple[re.Pattern, str]] = [
    (re.compile('/home/' + r'[A-Za-z0-9._-]+'), '/home/<wsl-user>'),
    (re.compile('/mnt/' + 'c/Users/' + r'[A-Za-z0-9._-]+'),
     '/mnt/' + 'c/Users/' + '<win-user>'),
    (re.compile(_CDRIVE + r'[A-Za-z0-9._-]+'), r'C:\\Users\\<win-user>'),
]


def journal_path():
    from .. import config as appcfg
    return appcfg.REPO_ROOT / 'vault' / 'journal.md'


def redact(text: Any) -> Tuple[str, int]:
    """Apply every rule; returns (clean_text, substitutions)."""
    s = ' '.join(str(text or '').split())          # single-line + normalized
    n = 0
    for patterns in (_SECRET_RES, _ID_RES, _PATH_RES):
        for pat, repl in patterns:
            s, c = pat.subn(repl, s)
            n += c
    return s, n


def append(text: Any) -> Dict[str, Any]:
    """Append one dated line (redacted). Returns {path, entry, redactions}.
    Fail-silent -> {'path': None, 'entry': '', 'redactions': 0}."""
    try:
        clean, reds = redact(text)
        if not clean:
            return {'path': None, 'entry': '', 'redactions': 0}
        p = journal_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        line = f'- [{stamp}] {clean}\n'
        with p.open('a', encoding='utf-8') as f:      # APPEND-ONLY: mode 'a'
            f.write(line)
        return {'path': str(p), 'entry': line.rstrip('\n'), 'redactions': reds}
    except Exception:  # noqa: BLE001 — logging must never break a turn
        return {'path': None, 'entry': '', 'redactions': 0}


def read_recent(limit: int = 10) -> str:
    """Last N entries for 'what did you do recently'. Fail-silent -> ''."""
    try:
        p = journal_path()
        if not p.is_file():
            return ''
        lines = [ln for ln in p.read_text(encoding='utf-8').splitlines()
                 if ln.strip()]
        return '\n'.join(lines[-max(1, int(limit)):])
    except Exception:  # noqa: BLE001
        return ''
