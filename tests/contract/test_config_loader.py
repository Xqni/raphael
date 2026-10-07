"""INTERFACES §c at the LOADER level: brain/router's load_config() must parse
the repo's config.yaml (base + profiles block) — this is the config the real
stack boots with.
"""

from brain.router.config import load_config


# PINNED STRICT 2026-10-06 (was xfail): router fixed the config loader
# (request qa-security -> router fix-config-loader — landed with router merge).
def test_load_config_parses_repo_config_yaml():
    cfg = load_config()
    assert 'zen_free' in cfg.providers.chain
    assert cfg.providers.allow_go_runtime is False
    assert cfg.providers.allow_paid_runtime is False
    assert cfg.local_model.ollama_url.startswith('http')


# PINNED STRICT 2026-10-06 (was xfail): profile overlay now applied by the
# loader (INTERFACES §c implemented — brain-core config loader + router parse).
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
