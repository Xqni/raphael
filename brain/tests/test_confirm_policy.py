"""Wave 5P P3 — user-editable confirmation policy (design-review findings
1-2: safety.confirm_policy was DEAD CONFIG and the code's real default
(allow-on-no-match) contradicted the config's declared default=confirm).

Ladder under test: policy classes (category/regex ids) -> regex classifier
-> declared default, the default applying ONLY to model-picked tools so
fastpath acts and plain chat stay act-first (autonomy split law 1).
Invalid policy values fail CLOSED to 'confirm'; 'never' refuses outright.
"""
import pytest

from brain import confirm as confirm_mod
from brain import config as appcfg
from brain import fastpath


def _policy(monkeypatch, default='confirm', classes=None):
    cfg = dict(appcfg.get_config())
    cfg['safety'] = dict(cfg.get('safety') or {})
    cfg['safety']['confirm_policy'] = {'default': default,
                                       'classes': classes or {}}
    monkeypatch.setattr(appcfg, 'get_config', lambda: cfg)


# ---- finding 2 pin: declared default is the REAL default for tools ---------
def test_default_confirm_gates_unclassified_model_picked_tool(monkeypatch):
    _policy(monkeypatch, default='confirm')
    d = confirm_mod.classify('summarize the deploy checklist',
                             tool='screenshot', model_picked=True)
    # by_policy=False: the default is the ABSENCE of classification — the
    # loop's registry force-gates still apply on top of it
    assert d.needs is True and d.by_policy is False
    assert d.risk == 'high'                 # AUD-09: tool-sourced = non-voice
    assert 'screenshot' in d.question       # honest question names the tool


def test_default_auto_allows_unclassified_model_picked_tool(monkeypatch):
    _policy(monkeypatch, default='auto')
    d = confirm_mod.classify('summarize the deploy checklist',
                             tool='screenshot', model_picked=True)
    assert d.needs is False and d.by_policy is False and d.refused is False


def test_default_never_refuses_unclassified_model_picked_tool(monkeypatch):
    _policy(monkeypatch, default='never')
    d = confirm_mod.classify('summarize the deploy checklist',
                             tool='screenshot', model_picked=True)
    assert d.needs is False and d.refused is True


def test_default_never_applies_to_fastpath_acts_only_via_model_picked():
    # fastpath (model_picked=False) never consults the declared default —
    # act-first is structural, not configurable away by omission
    d = confirm_mod.classify('open youtube.com', tool='launch_url')
    assert d.needs is False and d.refused is False


# ---- chat safety: the default must never confirm plain conversation --------
def test_plain_chat_never_confirms_even_with_default_confirm(monkeypatch):
    _policy(monkeypatch, default='confirm')
    assert confirm_mod.classify('hello there, how are you').needs is False
    assert confirm_mod.classify('').needs is False


# ---- policy classes outrank the regex (user-editable authority) ------------
def test_class_auto_overrides_risky_pattern(monkeypatch):
    _policy(monkeypatch, classes={'delete_files': 'auto'})
    d = confirm_mod.classify('delete the old log files',
                             tool='screenshot', model_picked=True)
    assert d.needs is False and d.by_policy is True and d.refused is False


def test_class_never_refuses_matched_action(monkeypatch):
    _policy(monkeypatch, classes={'delete_files': 'never'})
    d = confirm_mod.classify('delete the old log files')
    assert d.refused is True and d.needs is False
    assert 'delete_files' in d.reason


def test_class_confirm_asks_for_matched_action(monkeypatch):
    _policy(monkeypatch, classes={'delete_files': 'confirm'})
    d = confirm_mod.classify('delete the old log files')
    assert d.needs is True and d.by_policy is True
    assert 'delete files or data' in d.reason   # regex reason preserved


def test_confirm_category_is_the_first_policy_candidate(monkeypatch):
    # ToolSpec confirm category (e.g. open_path -> open_arbitrary_file)
    _policy(monkeypatch, classes={'open_arbitrary_file': 'auto'})
    d = confirm_mod.classify('open the thing', tool='open_path',
                             confirm_category='open_arbitrary_file')
    assert d.needs is False and d.by_policy is True


# ---- regex stays the classifier for ids the map does not name --------------
def test_unmapped_risky_tool_still_asks_via_regex(monkeypatch):
    _policy(monkeypatch, classes={'delete_files': 'confirm'})   # map exists
    d = confirm_mod.classify('run some shell command')          # other id
    assert d.needs is True and d.by_policy is False
    assert d.reason == 'run a privileged/system command'
    # no tool in play -> channel follows the confirm_actions list (not listed
    # -> low); the SAME text with a tool is non-voice per AUD-09
    d2 = confirm_mod.classify('run some shell command', tool='shell',
                              model_picked=True)
    assert d2.needs is True and d2.risk == 'high'


def test_risky_tool_name_still_classifies(monkeypatch):
    _policy(monkeypatch, classes={})
    d = confirm_mod.classify('do a thing', tool='files_delete')
    assert d.needs is True and d.action == 'delete_files'


# ---- invalid policy values fail CLOSED to confirm --------------------------
def test_invalid_default_fails_closed_to_confirm(monkeypatch):
    _policy(monkeypatch, default='banana')
    d = confirm_mod.classify('whatever', tool='screenshot', model_picked=True)
    assert d.needs is True and d.refused is False   # invalid = confirm, never open


def test_invalid_class_verdict_fails_closed_to_confirm(monkeypatch):
    _policy(monkeypatch, classes={'delete_files': 'maybe'})
    d = confirm_mod.classify('delete the old log files')
    assert d.needs is True and d.refused is False


def test_missing_policy_block_defaults_to_confirm(monkeypatch, tmp_path):
    # no safety.confirm_policy at all -> declared default is 'confirm'
    cfg = dict(appcfg.get_config())
    cfg.pop('safety', None)
    monkeypatch.setattr(appcfg, 'get_config', lambda: cfg)
    d = confirm_mod.classify('whatever', tool='screenshot', model_picked=True)
    assert d.needs is True


# ---- spoken surface: "what requires your confirmation?" --------------------
def test_policy_summary_answers_the_question(monkeypatch):
    _policy(monkeypatch, classes={'gui_submission': 'confirm',
                                  'purchase': 'never',
                                  'open_arbitrary_file': 'auto'})
    s = confirm_mod.policy_summary()
    assert 'gui_submission' in s and 'Confirmed first' in s
    assert 'purchase' in s and 'Blocked outright' in s
    assert 'open_arbitrary_file' in s and 'No questions asked' in s


def test_fastpath_intent_answers_confirm_question(monkeypatch):
    _policy(monkeypatch, classes={'gui_submission': 'confirm'})
    fastpath.register_builtin_intents()
    res = fastpath.run_intent('what requires your confirmation',
                              fastpath.IntentCtx())
    assert res is not None and res.tool is None
    assert 'gui_submission' in res.text


def test_repo_config_policy_is_sane():
    # the LIVE config block must parse to valid verdicts (dead-config fix)
    default, classes = confirm_mod.confirm_policy()
    assert default in confirm_mod.POLICY_VERDICTS
    assert classes, 'safety.confirm_policy.classes must be non-empty'
    assert all(v in confirm_mod.POLICY_VERDICTS for v in classes.values())
    assert 'gui_submission' in classes and 'open_arbitrary_file' in classes
