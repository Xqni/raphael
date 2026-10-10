"""Bug B router half (request APPROVED 2026-10-06): fastpath open+search
mapping. Exact mappings from docs/requests/router__to__brain-core__
fastpath-open-search-mapping.md — "open YouTube and search lo-fi" must reach
search_youtube, and existing open branches must not regress.

Plus the Wave-5P UX pairing (coord decision 2026-10-10): repeat open/search
with a browser foreground prefers pc-control's navigate_url (reuse the tab).
"""
import pytest

from brain import fastpath
from brain import foreground
from brain import tools as reg

# brain.loop registers the builtins at import; make this module self-contained
# (register is idempotent — dict overwrites).
fastpath.register_builtin_intents()


def _ctx():
    return fastpath.IntentCtx()


def test_open_youtube_and_search_maps_to_search_youtube():
    res = fastpath.run_intent('open youtube and search lo-fi', _ctx())
    assert res is not None
    assert res.tool == 'search_youtube'
    assert res.tool_args == {'query': 'lo-fi'}
    assert res.text == 'Searching YouTube for lo-fi…'
    assert res.task_kind == 'web'
    # case-insensitive site match, query keeps its inner words
    res = fastpath.run_intent('Open YouTube and search rain sounds', _ctx())
    assert res.tool == 'search_youtube'
    assert res.tool_args == {'query': 'rain sounds'}


def test_explicit_search_intents():
    for phrase in ('search lo-fi', 'search for lo-fi',
                   'search lo-fi on youtube', 'search for lo-fi on youtube',
                   'youtube search lo-fi'):
        res = fastpath.run_intent(phrase, _ctx())
        assert res is not None, phrase
        assert res.tool == 'search_youtube', phrase
        assert res.tool_args == {'query': 'lo-fi'}, (phrase, res.tool_args)
    # empty search falls through
    assert fastpath.run_intent('search ', _ctx()) is None


def test_existing_open_branches_unchanged():
    res = fastpath.run_intent('open chrome', _ctx())
    assert res.tool == 'open_app' and res.tool_args == {'name': 'chrome'}
    assert res.task_kind == 'system'
    res = fastpath.run_intent('open settings', _ctx())
    assert res.tool == 'open_app' and res.tool_args == {'name': 'settings'}
    res = fastpath.run_intent('open youtube.com', _ctx())
    assert res.tool == 'launch_url'
    assert res.tool_args == {'url': 'https://youtube.com'}
    assert res.task_kind == 'web'
    # non-youtube "and search" stays an app launch (approved patch scope)
    res = fastpath.run_intent('open google and search cats', _ctx())
    assert res.tool == 'open_app'
    assert res.tool_args == {'name': 'google and search cats'}


def test_search_youtube_is_registered_in_the_registry():
    from brain import tools as reg
    assert reg.get('search_youtube') is not None
    meta = reg.describe('search_youtube')
    assert meta['category'] == 'gui'


def test_empty_open_falls_through():
    assert fastpath.run_intent('open ', _ctx()) is None


# ---- Wave-5P UX pairing: repeat open/search prefers navigate-in-place ------
@pytest.fixture(autouse=True)
def _clean_foreground():
    foreground.reset_for_tests()
    yield
    foreground.reset_for_tests()


@pytest.fixture
def navigate_tool():
    """pc-control's navigate_url stand-in (their P0 half); removed after
    each test so no other module ever sees a phantom registry entry."""
    reg.register('navigate_url', lambda **kw: 'ok',
                 description='navigate in place (test double)',
                 category='gui')
    yield 'navigate_url'
    reg._registry.pop('navigate_url', None)
    reg._META.pop('navigate_url', None)


def test_repeat_open_with_browser_prefers_navigate(navigate_tool):
    foreground.set_foreground('YouTube - Google Chrome | chrome.exe')
    res = fastpath.run_intent('open youtube.com', _ctx())
    assert res.tool == 'navigate_url'
    assert res.tool_args == {'url': 'https://youtube.com'}
    assert res.task_kind == 'web'
    assert res.text == 'Navigating to youtube.com…'


def test_first_open_without_browser_keeps_launch_url(navigate_tool):
    # navigate_url IS registered but nothing is foreground -> FIRST open
    res = fastpath.run_intent('open youtube.com', _ctx())
    assert res.tool == 'launch_url'
    assert res.tool_args == {'url': 'https://youtube.com'}


def test_falls_back_to_launch_while_navigate_tool_unregistered(monkeypatch):
    # pairing window: pc-control's tool not merged yet -> launch_url, safe
    foreground.set_foreground('Inbox - Google Chrome | chrome.exe')
    monkeypatch.setattr(fastpath, '_have_tool', lambda name: False)
    res = fastpath.run_intent('open github.com', _ctx())
    assert res.tool == 'launch_url'
    assert res.tool_args == {'url': 'https://github.com'}


def test_title_only_browser_identity_reuses(navigate_tool):
    # legacy frame without the process half still matches on the title
    foreground.set_foreground('New Tab - Microsoft Edge')
    res = fastpath.run_intent('open example.com', _ctx())
    assert res.tool == 'navigate_url'


def test_non_browser_foreground_keeps_launch():
    foreground.set_foreground('notes.txt - Notepad | notepad.exe')
    res = fastpath.run_intent('open example.com', _ctx())
    assert res.tool == 'launch_url'


def test_ambiguous_title_needs_separator():
    # a media player showing "Grand Opera" must never fake a browser
    foreground.set_foreground('Grand Opera')
    assert fastpath._browser_reuse_available() is False
    foreground.set_foreground('Grand Opera | vlc.exe')
    assert fastpath._browser_reuse_available() is False
    foreground.set_foreground('Player - Opera')
    assert fastpath._browser_reuse_available() is True


def test_repeat_search_with_browser_navigates_to_results(navigate_tool):
    foreground.set_foreground('Music - Google Chrome | chrome.exe')
    res = fastpath.run_intent('search lo-fi beats', _ctx())
    assert res.tool == 'navigate_url'
    assert res.tool_args == {'url': 'https://www.youtube.com/results'
                                    '?search_query=lo-fi+beats'}
    assert res.text == 'Searching YouTube for lo-fi beats…'


def test_compound_youtube_search_with_browser_navigates(navigate_tool):
    foreground.set_foreground('Music - Google Chrome | chrome.exe')
    res = fastpath.run_intent('open youtube and search rain sounds', _ctx())
    assert res.tool == 'navigate_url'
    assert res.tool_args == {'url': 'https://www.youtube.com/results'
                                    '?search_query=rain+sounds'}
