"""file tools tests: roots confinement, secret refusal, trash (never delete),
restore roundtrip, caps. No network, no real home access."""
import pytest

from brain.tools import files as f


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    r = tmp_path / 'home'
    r.mkdir()
    monkeypatch.setattr(f, '_allowed_roots', lambda: [r.resolve()])
    monkeypatch.setattr(f, '_trash_root', lambda: tmp_path / 'trash')
    return r


def test_search_globs_and_skips_junk(root):
    (root / 'docs').mkdir()
    (root / 'docs' / 'report.pdf').write_text('x')
    (root / 'docs' / 'notes.txt').write_text('x')
    (root / '.git').mkdir()
    (root / '.git' / 'junk.pdf').write_text('x')
    out = f.file_search(str(root), '*.pdf')
    assert 'report.pdf' in out and 'junk.pdf' not in out
    assert 'no matches' in f.file_search(str(root), '*.mp3')
    # limit
    for i in range(10):
        (root / 'docs' / f'f{i}.log').write_text('x')
    assert len(f.file_search(str(root), '*.log', limit=3).splitlines()) == 3


def test_search_refuses_outside_roots_and_bad_root(root):
    with pytest.raises(ValueError):
        f.file_search('/etc', '*')
    with pytest.raises(ValueError):
        f.file_search(str(root / 'missing'), '*')
    with pytest.raises(ValueError):
        f.file_search(str(root), '')


def test_read_lines_offset_limit(root):
    p = root / 'a.txt'
    p.write_text('l1\nl2\nl3\nl4\nl5')
    out = f.file_read(str(p))
    assert 'l1' in out and 'lines 1-5 of 5' in out
    out = f.file_read(str(p), offset=2, limit=2)
    assert 'l3' in out and 'l4' in out and 'l2' not in out
    assert 'no lines at offset' in f.file_read(str(p), offset=99)


def test_read_refuses_binary_secret_outside_missing(root):
    (root / 'img.bin').write_bytes(b'\x00\x01\x02binary')
    with pytest.raises(ValueError):
        f.file_read(str(root / 'img.bin'))
    (root / '.env').write_text('SECRET=1')
    with pytest.raises(ValueError):
        f.file_read(str(root / '.env'))
    with pytest.raises(ValueError):
        f.file_read('/etc/passwd')
    with pytest.raises(ValueError):
        f.file_read(str(root / 'nope.txt'))


def test_read_is_capped(root, monkeypatch):
    monkeypatch.setattr(f, '_cfg',
                        lambda k, d: 50 if k == 'files.read_max_bytes' else d)
    (root / 'big.txt').write_text('x' * 5000)
    out = f.file_read(str(root / 'big.txt'))
    assert 'TRUNCATED' in out and len(out) < 700


def test_write_append_and_guards(root):
    out = f.file_write(str(root / 'n.txt'), 'hello')
    assert out.startswith('wrote 5 chars')
    out = f.file_write(str(root / 'n.txt'), 'world', append=True)
    assert 'appended' in out
    assert (root / 'n.txt').read_text() == 'helloworld'
    out = f.file_write(str(root / 'n.txt'), 'over')
    assert out.startswith('overwrote')
    with pytest.raises(ValueError):
        f.file_write(str(root / 'missing_dir' / 'x.txt'), 'x')
    with pytest.raises(ValueError):
        f.file_write(str(root / '.env'), 'TOKEN=x')      # never write secrets
    with pytest.raises(ValueError):
        f.file_write('/tmp/evil.txt', 'x')               # outside roots


def test_trash_and_restore_roundtrip(root):
    p = root / 'doc.txt'
    p.write_text('precious')
    out = f.file_trash(str(p))
    assert 'trashed' in out and not p.exists()           # moved, NOT deleted
    tid = out.split('-> ')[1].split(' ')[0]
    entry = (root.parent / 'trash') / tid
    assert (entry / 'doc.txt').read_text() == 'precious'  # recoverable content
    assert 'restored' in f.file_restore(tid)
    assert p.read_text() == 'precious'


def test_trash_guards(root):
    with pytest.raises(ValueError):
        f.file_trash(str(root / 'ghost.txt'))            # missing
    (root / '.env').write_text('X')
    with pytest.raises(ValueError):
        f.file_trash(str(root / '.env'))                 # secrets not trashable
    with pytest.raises(ValueError):
        f.file_restore('../etc')
    with pytest.raises(ValueError):
        f.file_restore('no_such_entry')
    # restore refuses when the origin exists again (no clobber)
    p = root / 'dup.txt'
    p.write_text('a')
    out = f.file_trash(str(p))
    tid = out.split('-> ')[1].split(' ')[0]
    p.write_text('new content already here')
    with pytest.raises(ValueError):
        f.file_restore(tid)


def test_registry_metadata_and_specs():
    from brain import tools as reg
    assert reg.describe('file_trash')['risky'] is True    # confirm-gated
    assert reg.describe('file_read')['risky'] is False
    assert reg.get('file_trash') is f.file_trash
    for name in ('file_search', 'file_read', 'file_write', 'file_trash',
                 'file_restore'):
        s = reg.describe(name)['schema']
        assert s['type'] == 'object' and s['additionalProperties'] is False
    with pytest.raises(reg.BadToolArgs):
        reg.validate_args('file_read', {'path': 'x', 'extra': 1})
