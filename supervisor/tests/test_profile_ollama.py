"""Profile awareness (WAVES.md): under cloud_temp the supervisor must NEVER
start Ollama / pull / warm local models; under local it does. Health/backoff
path untouched — these tests only exercise bring_up_wsl's call surface."""
import pytest

from supervisor import main as sup


class Recorder:
    def __init__(self):
        self.calls = []

    def wsl_run(self, cfg, *cmd, timeout=30, sudo=False):
        self.calls.append(tuple(str(c) for c in cmd))
        return 0, "LoadState=not-found"

    def has(self, needle):
        return any(needle in " ".join(c) for c in self.calls)

    def count(self, needle):
        return sum(1 for c in self.calls if needle in " ".join(c))


@pytest.fixture
def bringup(monkeypatch, tmp_path):
    """Patch every wsl-facing primitive; return (cfg, recorder, run)."""
    rec = Recorder()
    monkeypatch.setattr(sup, "find_wsl", lambda: "/usr/bin/wsl")
    monkeypatch.setattr(sup, "wsl_run", rec.wsl_run)

    def fake_wsl_state(cfg, unit, timeout=30):
        # real wsl_state delegates to wsl_run — record it like the real path
        rec.calls.append(("systemctl", "is-active", str(unit)))
        return "inactive"

    monkeypatch.setattr(sup, "wsl_state", fake_wsl_state)
    # brain unit absent -> process mode; ollama "installed" so a local-profile
    # run would actually reach its systemctl start.
    monkeypatch.setattr(
        sup, "unit_load_state",
        lambda cfg, unit, timeout=15: "loaded" if "ollama" in unit
        else "not-found")
    monkeypatch.setattr(sup, "launch_brain",
                        lambda cfg, log: "BRAIN_SPAWNED")
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)

    def run(profile):
        cfg, _ = sup.load_config()
        cfg["profile"] = profile
        procs = {}
        ok = sup.bring_up_wsl(cfg, log, procs)
        return ok, procs

    return run, rec


def test_cloud_temp_never_touches_ollama(bringup):
    run, rec = bringup
    ok, procs = run("cloud_temp")
    assert ok is True                       # brain spawn still happens
    assert procs["brain"] == "BRAIN_SPAWNED"
    assert rec.count("ollama") == 0, rec.calls   # no probe, no start
    # and no local-model-ish calls at all
    joined = " ".join(" ".join(c) for c in rec.calls)
    assert "pull" not in joined and "keep_alive" not in joined


def test_local_profile_does_start_ollama(bringup):
    run, rec = bringup
    ok, _ = run("local")
    assert ok is True
    assert rec.count("ollama") >= 2          # is-active probe + start
    assert rec.has("start") and rec.has("ollama")
