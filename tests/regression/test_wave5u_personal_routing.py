"""Wave 5U Wave A — personal-data routing gate (qa-security §5.5 task 5).

Contract (config.yaml providers, Wave 5U P2):
- `providers.personal_ok = [go, ollama]` — personal memory categories may enter
  prompts ONLY for these providers; never for zen_free (or any free tier).
- `providers.allow_free_models_for_personal_data = false` — personal data
  skips the free tier entirely (router `_skip_free`, AUD-04, LANDED).

These are STRICT config pins: the routing authority may not silently add a
free provider to personal_ok, nor re-enable free-tier personal data. The
router-side mock-spy (assert zen_free is never SELECTED for a personal payload)
activates once the router consumes `personal_ok` (router lane P2); the
`_skip_free` behavior it relies on is already landed and pinned here at the
config boundary.
"""
import yaml

from brain import config as cfg

PROV = yaml.safe_load((cfg.REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))["providers"]


def test_personal_ok_excludes_free_providers():
    """zen_free (free tier) must NEVER be in personal_ok."""
    personal_ok = set(PROV.get("personal_ok") or [])
    assert "zen_free" not in personal_ok, \
        f"zen_free in personal_ok — personal data would reach a free provider: {personal_ok}"
    # the approved local/paid set (Wave 5U P2)
    assert personal_ok == {"go", "ollama"}, personal_ok


def test_free_tier_personal_data_is_disabled():
    """The `_skip_free` gate (AUD-04) is armed: personal data skips free models."""
    assert PROV.get("allow_free_models_for_personal_data") is False, \
        "allow_free_models_for_personal_data was re-enabled"


def test_ollama_stays_out_of_the_cloud_chain():
    """ollama is a personal_ok LOCAL provider but must not be in the default
    cloud chain (cloud_temp keeps ollama OFF)."""
    chain = PROV.get("chain") or []
    assert "ollama" not in chain
