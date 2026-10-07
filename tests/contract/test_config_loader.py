"""INTERFACES §c at the LOADER level: brain/router's load_config() must parse
the repo's config.yaml (base + profiles block) — this is the config the real
stack boots with.
"""
import pytest

from brain.router.config import load_config


@pytest.mark.xfail(strict=False,
                   reason='_simple_yaml_load mis-parses config.yaml since the '
                          'profiles block landed: cfg["providers"] becomes a '
                          'str and load_config() raises AttributeError — '
                          'get_router()/llm.plan crash for the REAL stack '
                          '(request: qa-security -> router fix-config-loader)')
def test_load_config_parses_repo_config_yaml():
    cfg = load_config()                      # crashes today
    assert 'zen_free' in cfg.providers.chain
    assert cfg.providers.allow_go_runtime is False
    assert cfg.providers.allow_paid_runtime is False
    assert cfg.local_model.ollama_url.startswith('http')


@pytest.mark.xfail(strict=False,
                   reason='profile overlay per INTERFACES §c is not applied '
                          'by the router config loader yet (brain-core owns '
                          'the shared loader; router keeps its own parse)')
def test_profile_overlay_respected():
    import os
    old = os.environ.get('RAPHAEL_PROFILE')
    os.environ['RAPHAEL_PROFILE'] = 'local'
    try:
        cfg = load_config()
        assert 'ollama' in cfg.providers.chain      # local profile chain
    finally:
        if old is None:
            os.environ.pop('RAPHAEL_PROFILE', None)
        else:
            os.environ['RAPHAEL_PROFILE'] = old
