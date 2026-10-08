"""F-2 acquisition tests: flag OFF = zero side effects everywhere; flag ON
(monkeypatched, as if the user enabled it) = observe -> sandbox draft ->
injected-runner test -> approval (still below gate) -> human-only publish.
Mock tests only — nothing is ever executed by the module itself."""
import pytest

import brain.memory as acq_mod_probe  # noqa: F401 — package import sanity
from brain.memory import acquisition as acq
from brain.memory import skills


@pytest.fixture(autouse=True)
def _skills_dirs(tmp_path, monkeypatch):
    live = tmp_path / 'skills'
    live.mkdir()
    monkeypatch.setattr(skills, '_cfg',
                        lambda k, default: str(live) if k == 'skills.dir'
                        else default)
    acq._observed.clear()                          # per-test observation state
    yield live
    acq._observed.clear()


def _flag(monkeypatch, on: bool, repeats: int = 3):
    monkeypatch.setattr(
        acq, '_cfg',
        lambda k, default: (on if k == 'skills.acquisition_enabled'
                            else (repeats if k == 'skills.acquisition_min_repeats'
                                  else default)))


def test_flag_off_means_zero_side_effects(tmp_path):
    assert acq.enabled() is False                      # default config value
    r = acq.observe_failure('rebuild the widget', error='boom')
    assert r['enabled'] is False and 'reason' in r
    r = acq.maybe_draft('rebuild the widget', procedure='p')
    assert r['enabled'] is False
    assert not (tmp_path / 'skills' / '.drafts').exists()   # NOTHING written
    assert acq.test_draft('anything')['enabled'] is False
    assert acq.submit_for_approval('anything')['enabled'] is False
    # observation counter never even recorded
    assert acq._observed == {}


def test_observe_counts_to_threshold(monkeypatch):
    _flag(monkeypatch, on=True, repeats=3)
    task = 'Fix the flaky widget test'
    assert acq.observe_failure(task, error='e1')['ready'] is False
    assert acq.observe_failure(task, error='e2')['ready'] is False
    r = acq.observe_failure(task, error='e3')
    assert r['ready'] is True and r['count'] == 3
    # signature normalization: case/punctuation variants count TOGETHER
    r = acq.observe_failure('fix the FLAKY widget test!', error='e4')
    assert r['count'] == 4 and r['ready'] is True


def test_draft_lands_in_sandbox_and_gate_excludes_it(monkeypatch):
    _flag(monkeypatch, on=True)
    task = 'Rotate the certificates quarterly'
    acq.observe_failure(task, error='expired cert')
    acq.observe_failure(task, error='expired cert')
    acq.observe_failure(task, error='expired cert')
    r = acq.maybe_draft(task, error='expired cert',
                        procedure='1. renew\n2. redeploy',
                        verification='certCheck --all exits 0')
    assert r['status'] == 'drafted'
    name = r['name']
    assert str(acq._drafts_dir()) in r['sandbox']
    draft_file = acq._drafts_dir() / name / 'SKILL.md'
    assert draft_file.is_file()
    # sandboxed: NOT in the live skills/ tree
    assert not (acq._skills.skills_dir() / name / 'SKILL.md').exists()
    # draft + confidence 0.0 -> never auto-injected (existing gate)
    rec = skills.get_skill(name, directory=acq._drafts_dir())
    assert rec['status'] == 'draft' and rec['confidence'] == 0.0
    assert skills.active_skills() == []
    # dedup inherited: re-drafting the same thing bumps instead of stacking
    r2 = acq.maybe_draft(task, error='again',
                         procedure='1. renew\n2. redeploy',
                         verification='certCheck --all exits 0')
    assert r2['status'] == 'drafted' and r2['name'] == name
    rows = [d for d in skills.list_skills() if d['name'] == name]
    assert rows and rows[0]['dedup_hits'] >= 1


def test_maybe_draft_never_fires_without_observation(monkeypatch):
    _flag(monkeypatch, on=True)
    r = acq.maybe_draft('never seen task')
    assert r['status'] == 'not_ready'


def test_test_draft_never_executes_without_runner(monkeypatch):
    _flag(monkeypatch, on=True)
    task = 'compile the firmware'
    for _ in range(3):
        acq.observe_failure(task, error='cc failed')
    name = acq.maybe_draft(task, error='cc failed',
                           verification='make && ./test')['name']
    out = acq.test_draft(name)                        # no runner
    assert out['status'] == 'skipped'
    assert 'never auto-executes' in out['reason']


def test_test_draft_uses_only_injected_runner(monkeypatch):
    _flag(monkeypatch, on=True)
    task = 'deploy the docs'
    for _ in range(3):
        acq.observe_failure(task, error='404')
    name = acq.maybe_draft(task, verification='curl -I returns 200')['name']
    seen = {}

    def runner(verification_text):
        seen['v'] = verification_text
        return 'ok'
    out = acq.test_draft(name, runner=runner)
    assert out['status'] == 'passed' and 'curl -I' in seen['v']
    # runner raising = failed test, not a crash
    out = acq.test_draft(name, runner=lambda v: (_ for _ in ()).throw(
        RuntimeError('boom')))
    assert out['status'] == 'failed' and 'boom' in out['error']


def test_approval_is_human_two_step(monkeypatch):
    _flag(monkeypatch, on=True)
    task = 'compress the archives'
    for _ in range(3):
        acq.observe_failure(task, error='zip missing')
    name = acq.maybe_draft(task, error='zip missing',
                           verification='zip -T ok')['name']
    appr = acq.submit_for_approval(name)
    assert appr['status'] == 'awaiting_approval' and 'set_status' in appr['prompt']
    assert skills.active_skills() == []               # still below the gate
    # human approves: finalize moves sandbox -> live tree, STILL draft/below-gate
    fin = acq.finalize_draft(name)
    assert fin['status'] == 'finalized'
    assert (acq._skills.skills_dir() / name / 'SKILL.md').is_file()
    assert not (acq._drafts_dir() / name).exists()
    assert skills.active_skills() == []               # move alone activates NOTHING
    # the ONLY activation path: human two-step on the existing API
    skills.set_status(name, 'published')
    skills.set_confidence(name, 0.9)
    assert [s['name'] for s in skills.active_skills()] == [name]


def test_flag_off_midway_blocks_everything(monkeypatch):
    _flag(monkeypatch, on=True)
    task = 'midway task'
    for _ in range(3):
        acq.observe_failure(task, error='x')
    _flag(monkeypatch, on=False)                      # user flips it back
    assert acq.maybe_draft(task)['enabled'] is False
    assert acq.test_draft('x')['enabled'] is False
    assert acq.submit_for_approval('x')['enabled'] is False
    # but the human can still SEE existing sandbox content
    assert isinstance(acq.list_drafts(), list)
