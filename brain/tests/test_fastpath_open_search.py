"""Bug B router half (request APPROVED 2026-10-06): fastpath open+search
mapping. Exact mappings from docs/requests/router__to__brain-core__
fastpath-open-search-mapping.md — "open YouTube and search lo-fi" must reach
search_youtube, and existing open branches must not regress."""
from brain import fastpath

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
