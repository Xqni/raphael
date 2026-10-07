"""Skills loader tests: parse, gate, dedup, counters, review/delete.
All files go to a per-test tmp dir (never the repo's skills/)."""
import pytest

from brain.memory import skills


def _dir(tmp_path):
    d = tmp_path / 'skills'
    d.mkdir()
    return d


def _mk(d, name, body, **meta):
    fm = {'name': name, 'description': f'{name} description',
          'status': 'draft', 'confidence': 0.0, 'source': 'learned',
          'category': 'general', 'tags': [], 'version': '1'}
    fm.update(meta)
    import yaml
    p = d / name / 'SKILL.md'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('---\n' + yaml.safe_dump(fm, sort_keys=False) +
                 '---\n' + body, encoding='utf-8')
    return p


def test_parse_valid_skill(tmp_path):
    d = _dir(tmp_path)
    _mk(d, 'alpha', '## When to Use\nx\n## Procedure\ny',
        description='does alpha things', status='published', confidence=0.8)
    rec = skills.parse_skill((d / 'alpha' / 'SKILL.md').read_text())
    assert rec['name'] == 'alpha'
    assert rec['status'] == 'published'
    assert rec['confidence'] == 0.8
    assert '## When to Use' in rec['body']
    assert len(rec['content_hash']) == 64


def test_parse_rejects_malformed():
    with pytest.raises(skills.SkillError):
        skills.parse_skill('no frontmatter here')
    with pytest.raises(skills.SkillError):
        skills.parse_skill('---\nname: x\nstatus: exploded\n---\nbody')
    with pytest.raises(skills.SkillError):
        skills.parse_skill('---\nname: ../evil\n---\nbody')       # path trick
    with pytest.raises(skills.SkillError):
        skills.parse_skill('---\nname: ok\nconfidence: 7\n---\nbody')
    with pytest.raises(skills.SkillError):
        skills.parse_skill('---\nnot: a: mapping: [\n---\n')       # bad yaml


def test_sync_mirrors_files_and_records_invalid(tmp_path):
    d = _dir(tmp_path)
    _mk(d, 'good', 'body text')
    (d / 'broken').mkdir()
    (d / 'broken' / 'SKILL.md').write_text('garbage', encoding='utf-8')
    out = skills.sync(directory=d)
    assert out['loaded'] == 1 and out['invalid'] == 1
    assert any('broken' in k for k in out['errors'])
    names = [r['name'] for r in skills.list_skills()]
    assert 'good' in names
    # resync of unchanged content keeps sidecar counters
    skills.bump_skill_use('good')
    skills.sync(directory=d)
    row = [r for r in skills.list_skills() if r['name'] == 'good'][0]
    assert row['uses'] == 1


def test_create_skill_writes_draft_and_validates_name(tmp_path):
    d = _dir(tmp_path)
    name = skills.create_skill('new_skill', 'unique content about rockets',
                               '## Procedure\nbuild it', directory=d)
    assert name == 'new_skill'
    rec = skills.get_skill('new_skill', directory=d)
    assert rec['status'] == 'draft' and rec['confidence'] == 0.0
    with pytest.raises(skills.SkillError):
        skills.create_skill('../escape', 'x', 'y', directory=d)
    with pytest.raises(skills.SkillError):
        skills.create_skill('ok_name', '', '   ', directory=d)     # empty content
    with pytest.raises(skills.SkillError):
        skills.create_skill('ok_name', 'desc', 'body', status='live')


def test_dedup_bumps_instead_of_duplicating(tmp_path):
    d = _dir(tmp_path)
    skills.create_skill('orig', 'deploy pipeline notes for staging',
                        '## Procedure\ndeploy the pipeline', directory=d)
    # near-identical second attempt -> dedup into 'orig'
    out = skills.create_skill('copycat', 'deploy pipeline notes for staging',
                              '## Procedure\ndeploy the pipeline', directory=d)
    assert out == 'orig'
    assert not (d / 'copycat').exists()
    row = [r for r in skills.list_skills() if r['name'] == 'orig'][0]
    assert row['dedup_hits'] == 1 and row['uses'] == 1
    # dissimilar skill passes dedup
    out2 = skills.create_skill('totally_other', 'watering schedule for succulents',
                               '## Procedure\nwater rarely', directory=d)
    assert out2 == 'totally_other'


def test_confidence_gate_excludes_drafts_and_low_confidence(tmp_path, monkeypatch):
    d = _dir(tmp_path)
    monkeypatch.setattr(skills, '_cfg',
                        lambda k, default: str(d) if k == 'skills.dir'
                        else default)
    skills.create_skill('draft_one', 'draft skill text', 'body-a', directory=d)
    skills.create_skill('low_one', 'low confidence skill text', 'body-b',
                        confidence=0.2, directory=d)
    skills.create_skill('pub_low', 'published but low text', 'body-c',
                        confidence=0.3, status='published', directory=d)
    skills.create_skill('pub_ok', 'published good skill text', 'body-d',
                        confidence=0.9, status='published', directory=d)
    active = [s['name'] for s in skills.active_skills()]
    assert active == ['pub_ok']                    # THE GATE
    # bumping counters never opens the gate
    skills.bump_skill_use('draft_one')
    assert [s['name'] for s in skills.active_skills()] == ['pub_ok']
    # widening confidence does NOT bypass the status gate: drafts stay out,
    # published rows appear (separate knobs, both enforced)
    assert sorted(s['name'] for s in skills.active_skills(min_confidence=0.0)) == \
        ['pub_low', 'pub_ok']


def test_gate_publish_flow_updates_file_and_index(tmp_path, monkeypatch):
    d = _dir(tmp_path)
    monkeypatch.setattr(skills, '_cfg',
                        lambda k, default: str(d) if k == 'skills.dir'
                        else default)
    skills.create_skill('wip', 'learning in progress skill', 'body', directory=d)
    assert skills.active_skills() == []
    assert skills.set_confidence('wip', 0.7) is True
    assert skills.set_status('wip', 'published') is True
    # file reflects the promotion (no drift between file and index)
    rec = skills.get_skill('wip', directory=d)
    assert rec['status'] == 'published' and rec['confidence'] == 0.7
    assert [s['name'] for s in skills.active_skills()] == ['wip']
    with pytest.raises(skills.SkillError):
        skills.set_status('wip', 'exploded')
    with pytest.raises(skills.SkillError):
        skills.set_confidence('wip', 9)
    assert skills.set_status('missing', 'published') is False


def test_delete_skill_removes_file_and_row(tmp_path):
    d = _dir(tmp_path)
    skills.create_skill('gone', 'temporary skill', 'body', directory=d)
    assert (d / 'gone' / 'SKILL.md').is_file()
    assert skills.delete_skill('gone') is True
    assert not (d / 'gone' / 'SKILL.md').exists()
    assert skills.get_skill('gone', directory=d) is None
    assert skills.delete_skill('gone') is False      # already gone
    assert skills.delete_skill('../trick') is False  # name guard


def test_active_skills_fail_silent_on_db_error(monkeypatch):
    def _raise():
        raise RuntimeError('db gone')
    import brain.memory as mem
    monkeypatch.setattr(mem, 'get_conn', _raise)
    assert skills.active_skills() == []
    assert skills.list_skills() == []
    skills.bump_skill_use('whatever')                # no raise
