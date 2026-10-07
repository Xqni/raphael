"""Report-format delivery act (Wave 5): fixed-directory save, slugified
atomic writes, list semantics, content kept out of the action log."""
import json

import pytest

from body.win import actions

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _isolated_reports(fake, tmp_path):
    fake.reports_path = tmp_path / 'reports'
    return fake.reports_path


async def test_save_writes_file_and_returns_truthful_result(actlog, fake):
    body = '# Findings\n- risk 1\nconfidence: 0.8\nnext: patch'
    res = await actions.dispatch(
        'report', {'op': 'save', 'title': 'Q3 Report: Risks!', 'body': body},
        job='j1')
    assert res['ok'], res
    out = res['result']
    assert out['name'].endswith('.md')
    assert 'q3-report-risks' in out['name']
    assert out['bytes'] == len(body.encode('utf-8'))
    assert out['lines'] == 4
    written = (fake.reports_path / out['name']).read_text(encoding='utf-8')
    assert written == body                       # content byte-identical
    assert not list(fake.reports_path.glob('*.part')), 'atomic write left debris'


async def test_title_never_becomes_a_path(actlog, fake):
    res = await actions.dispatch(
        'report', {'op': 'save', 'title': '../../../etc/passwd',
                   'body': 'x'}, job='j2')
    assert res['ok'], res
    name = res['result']['name']
    assert '..' not in name and '/' not in name and '\\' not in name
    assert (fake.reports_path / name).is_file()  # inside the fixed dir only


async def test_json_format_validated_and_saved(actlog, fake):
    bad = await actions.dispatch(
        'report', {'op': 'save', 'title': 'bad', 'body': 'nope',
                   'format': 'json'}, job='j3')
    assert bad['ok'] is False and bad['error'].startswith('E_BAD_MSG')
    assert fake.reports_path.exists() is False or \
        not list(fake.reports_path.glob('*.json'))

    good = await actions.dispatch(
        'report', {'op': 'save', 'title': 'data', 'body': '{"a": 1}',
                   'format': 'json'}, job='j4')
    assert good['ok'] and good['result']['name'].endswith('.json')


async def test_same_second_saves_never_collide(actlog, fake):
    first = await actions.dispatch(
        'report', {'op': 'save', 'title': 'dup', 'body': 'one'}, job='j5')
    second = await actions.dispatch(
        'report', {'op': 'save', 'title': 'dup', 'body': 'two'}, job='j6')
    assert first['ok'] and second['ok']
    assert first['result']['name'] != second['result']['name']
    assert second['result']['name'].endswith('-2.md')
    assert (fake.reports_path / second['result']['name']).read_text() == 'two'


async def test_list_newest_first_and_ignores_debris(actlog, fake):
    empty = await actions.dispatch('report', {'op': 'list'}, job='j7')
    assert empty['ok'] and empty['result'] == {'count': 0, 'reports': []}

    a = await actions.dispatch(
        'report', {'op': 'save', 'title': 'a', 'body': 'first'}, job='j8')
    b = await actions.dispatch(
        'report', {'op': 'save', 'title': 'b', 'body': 'second'}, job='j9')
    fake.reports_path.joinpath('notes.png').write_bytes(b'\x89PNG')
    fake.reports_path.joinpath('half.md.part').write_text('x')

    listed = await actions.dispatch('report', {'op': 'list'}, job='j10')
    assert listed['ok']
    names = [r['name'] for r in listed['result']['reports']]
    assert listed['result']['count'] == 2
    assert set(names) == {a['result']['name'], b['result']['name']}
    mtimes = [r['mtime'] for r in listed['result']['reports']]
    assert mtimes == sorted(mtimes, reverse=True), 'newest first required'


async def test_body_never_reaches_the_action_log(actlog, fake):
    secret_finding = 'SECRET-FINDING user password hunter2 in vault.log'
    res = await actions.dispatch(
        'report', {'op': 'save', 'title': 'audit', 'body': secret_finding},
        job='j11')
    assert res['ok']
    logged = actlog.read_text()
    assert secret_finding not in logged, 'report body leaked into action log'
    line = json.loads(logged.splitlines()[-1])
    assert line['args']['body'] == '[len=%d]' % len(secret_finding)
    assert line['args']['title'] == 'audit'      # title stays useful for the viewer


async def test_body_over_cap_refused(actlog, fake):
    res = await actions.dispatch(
        'report', {'op': 'save', 'title': 'big', 'body': 'x' * 400001},
        job='j12')
    assert res['ok'] is False and 'exceeds 400000' in res['error']
    assert not fake.reports_path.exists()


async def test_list_takes_no_save_fields(actlog, fake):
    res = await actions.dispatch('report', {'op': 'list', 'title': 'x'},
                                 job='j13')
    assert res['ok'] is False and 'no title/body/format' in res['error']
