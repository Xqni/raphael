"""Wave-5P P7 tests: her journal — append format, redaction, read-back,
append-only. Uses a TMP journal (never the real repo vault/)."""
import re

import pytest

from brain.memory import journal

_LINE = re.compile(r'^- \[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\] .+$')


@pytest.fixture(autouse=True)
def p(tmp_path, monkeypatch):
    target = tmp_path / 'vault' / 'journal.md'
    monkeypatch.setattr(journal, 'journal_path', lambda: target)
    return target


def test_append_creates_file_in_dated_format(p):
    r = journal.append('landed the slot feature')
    assert r['path'].endswith('vault/journal.md')
    assert _LINE.match(r['entry'])                   # - [ISO] text
    assert 'landed the slot feature' in r['entry']
    assert p.is_file()


def test_append_only_preserves_existing_content(p):
    from pathlib import Path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('- [2020-01-01T00:00:00] PREEXISTING LINE\n',
                 encoding='utf-8')
    journal.append('second entry')
    journal.append('third entry')
    text = p.read_text(encoding='utf-8')
    assert text.startswith('- [2020-01-01T00:00:00] PREEXISTING LINE\n')
    assert text.count('\n- [') == 2
    # structural append-only: the module only ever opens the journal with 'a'
    src = Path(journal.__file__).read_text(encoding='utf-8')
    assert "open('a'" in src
    body = src.split('def read_recent')[0]
    assert 'write_text(' not in body and "open('w'" not in body \
        and 'open("w"' not in body             # no overwrite path in code


def test_redaction_of_secrets_ids_and_paths(p):
    r = journal.append(
        'deployed with ghp_abcdefghijklmnopqrstuvwxyz0123456789, '
        'password=hunter2, owner dami on /home/dami/raphael, '
        'win box C:\\Users\\jxesu, repo Xqni/raphael, '
        'github_pat_abcdefghijklmno123456, AKIA1234567890ABCDEF')
    text = p.read_text(encoding='utf-8')
    for leak in ('ghp_abcdefgh', 'hunter2', 'dami', '/home/dami',
                 'jxesu', 'Xqni', 'github_pat_', 'AKIA1234567890'):
        assert leak not in text, leak
    assert '***REDACTED***' in text
    assert '<wsl-user>' in text and '<win-user>' in text and '<gh-owner>' in text
    assert r['redactions'] >= 5


def test_redact_unit_table():
    cases = [
        ('token=abc123def456', '***REDACTED***'),
        ('user dami says hi', '<wsl-user>'),
        ('path /home/dami/x', '/home/<wsl-user>/x'),
        ('C:\\Users\\jxesu\\Desktop', 'C:\\Users\\<win-user>\\Desktop'),
        ('ghp_' + 'a' * 40, '***REDACTED***'),
        ('nothing sensitive here', 'nothing sensitive here'),
    ]
    for raw, expect in cases:
        out, _n = journal.redact(raw)
        assert expect in out, (raw, out)


def test_entry_is_single_line_even_with_newlines(p):
    r = journal.append('line one\nline two\n\nline three')
    assert '\n' not in r['entry'].strip()
    assert len([ln for ln in p.read_text().splitlines() if ln.strip()]) == 1


def test_read_recent_and_empty_states(p):
    assert journal.read_recent() == ''                 # missing file
    for i in range(5):
        journal.append(f'entry {i}')
    recent = journal.read_recent(limit=2)
    lines = [ln for ln in recent.splitlines() if ln]
    assert len(lines) == 2 and 'entry 4' in lines[-1] and 'entry 3' in lines[-2]
    assert journal.read_recent(limit=99).count('- [') == 5


def test_append_fail_silent_on_broken_path(monkeypatch):
    def _boom():
        raise OSError('vault unavailable')
    monkeypatch.setattr(journal, 'journal_path', _boom)
    r = journal.append('anything')
    assert r == {'path': None, 'entry': '', 'redactions': 0}   # never raises
    assert journal.read_recent() == ''
