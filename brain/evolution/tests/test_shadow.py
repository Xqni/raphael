"""Shadow-run tests (design 01 §3). Real subprocess pytest under
RAPHAEL_INSTANCE=shadow — proves the merged shadow row works end-to-end
without spawning any server (AGENT_RULES §5 / rule 14)."""
import sys

from brain.evolution import shadow as S


def test_shadow_env_sets_instance_and_drops_overrides(monkeypatch):
    monkeypatch.setenv("RAPHAEL_INSTANCE", "main")
    monkeypatch.setenv("RAPHAEL_PORT", "8765")
    monkeypatch.setenv("RAPHAEL_PROFILE", "local")
    env = S.shadow_env()
    assert env["RAPHAEL_INSTANCE"] == "shadow"
    assert "RAPHAEL_PORT" not in env and "RAPHAEL_PROFILE" not in env


def test_verify_instance_derivation_real_row():
    """REAL check: the merged ('shadow', 8911, 11) row derives §d values."""
    info = S.verify_instance_derivation(sys.executable)
    assert info.get("ok"), info
    assert info["instance"] == "shadow"
    assert info["port"] == 8911


def test_run_tests_under_shadow_instance(tmp_path):
    """REAL shadow run: one small pytest file in a subprocess with the
    shadow env. No server, no network, ~1s."""
    result = S.run_tests(
        S.REPO_ROOT,
        ["brain/evolution/tests/test_zones.py"],
        python=sys.executable,
        timeout=300,
        extra_args=["-p", "no:cacheprovider"],
    )
    assert result["instance"] == "shadow"
    assert result["derivation"]["ok"], result["derivation"]
    assert result["rc"] == 0, result["output"][-2000:]
    assert result["ok"] is True
    assert "passed" in result["output"]


def test_run_tests_refuses_when_derivation_fails(monkeypatch):
    """Fail-closed: broken derivation ⇒ refused run, never a blind pytest."""
    monkeypatch.setattr(S, "verify_instance_derivation",
                        lambda python=None: {"ok": False, "error": "row missing"})
    result = S.run_tests(S.REPO_ROOT, ["brain/evolution/tests/test_zones.py"])
    assert result["ok"] is False
    assert result["rc"] is None
    assert "refused" in result["error"]
