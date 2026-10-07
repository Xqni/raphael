"""Wave-4 skill aging audit + dedup-hardening tests."""
import datetime as dt

import yaml

import brain.memory as mem
from brain.memory import skills


def _dir(tmp_path):
    d = tmp_path / 'skills'
    d.mkdir()
    return d


def _backdate(name, days):
    conn = mem.get_conn()
    try:
        stamp = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                 - dt.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        conn.execute('UPDATE skills_index SET created_at = ? WHERE name = ?',
                     (stamp, name))
        conn.commit()
    finally:
        conn.close()


def _cfg_patch(monkeypatch, d):
    monkeypatch.setattr(
        skills, '_cfg',
        lambda k, default: str(d) if k == 'skills.dir' else
        (30 if k == 'skills.audit_grace_days' else default))


def test_audit_demotes_stale_unused_published(tmp_path, monkeypatch):
    d = _dir(tmp_path)
    _cfg_patch(monkeypatch, d)
    skills.create_skill('stale_one', 'stale published skill', 'body-1',
                        status='published', confidence=0.9, directory=d)
    _backdate('stale_one', 90)
    assert [s['name'] for s in skills.active_skills()] == ['stale_one']

    report = skills.audit_skills()
    assert report['demoted'] == ['stale_one']         # never used + 90d > 30d
    assert report['grace_days'] == 30
    # gate closed for injection AND the FILE reflects the demotion (reviewable)
    assert skills.active_skills() == []
    assert skills.get_skill('stale_one', directory=d)['status'] == 'draft'


def test_audit_keeps_used_young_and_drafts(tmp_path, monkeypatch):
    d = _dir(tmp_path)
    _cfg_patch(monkeypatch, d)
    skills.create_skill('used_old', 'used skill', 'body-u',
                        status='published', confidence=0.9, directory=d)
    skills.bump_skill_use('used_old')
    skills.bump_skill_use('used_old')
    _backdate('used_old', 90)
    skills.create_skill('fresh_one', 'fresh skill', 'body-f',
                        status='published', confidence=0.9, directory=d)
    skills.create_skill('draft_one', 'draft skill', 'body-d', directory=d)
    _backdate('draft_one', 90)

    report = skills.audit_skills()
    assert report['demoted'] == []
    assert set(report['kept']) == {'used_old', 'fresh_one', 'draft_one'}
    names = [s['name'] for s in skills.active_skills()]
    assert 'used_old' in names and 'fresh_one' in names   # draft stays out


def test_audit_never_deletes_and_finds_on_disk_duplicates(tmp_path, monkeypatch):
    d = _dir(tmp_path)
    _cfg_patch(monkeypatch, d)
    # created through the API (dedup-clean at that moment)
    skills.create_skill('orig_form', 'deploy pipeline for staging builds',
                        '## Procedure\ndeploy the pipeline', directory=d)
    # duplicate planted BYPASSING create (already on disk — the case the
    # creation-time dedup cannot see)
    p = d / 'planted_dup' / 'SKILL.md'
    p.parent.mkdir(parents=True)
    p.write_text('---\n' + yaml.safe_dump({
        'name': 'planted_dup',
        'description': 'deploy pipeline for staging builds',
        'status': 'draft', 'confidence': 0.0, 'source': 'learned',
        'category': 'general', 'tags': [], 'version': '1'}, sort_keys=False)
        + '---\n## Procedure\ndeploy the pipeline', encoding='utf-8')
    skills.sync(directory=d)

    report = skills.audit_skills()
    assert report['duplicates'], 'planted duplicate not detected'
    pair = report['duplicates'][0]
    assert {pair['a'], pair['b']} == {'orig_form', 'planted_dup'}
    assert pair['similarity'] >= 0.82
    # report-only: NEITHER file was touched or deleted
    assert (d / 'orig_form' / 'SKILL.md').is_file()
    assert (d / 'planted_dup' / 'SKILL.md').is_file()
    assert len(skills.list_skills()) == 2


def test_audit_fail_silent_on_db_error(monkeypatch):
    def _raise():
        raise RuntimeError('db gone')
    monkeypatch.setattr(mem, 'get_conn', _raise)
    assert skills.audit_skills() == {}
    assert skills.find_duplicates() == []
