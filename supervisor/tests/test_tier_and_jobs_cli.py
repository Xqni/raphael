"""Wave 5 infra plumbing tests: persona-tier runtime switch (safe restart
semantics), jobs --wait (simulation supervision), shadow-instance (8911)
readiness. Synthetic: stdlib mock brain, no servers spawned, live stack
untouched."""
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from supervisor import instance as im
from supervisor import main as sup

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "raphael_cli_under_test", _ROOT / "scripts" / "raphael_cli.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


# --------------------------------------------------------------------------
# Mock brain (health + /jobs list + dynamic single-job states)
# --------------------------------------------------------------------------
class _Brain(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, code, obj):
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        st = self.server.state
        if self.path == "/health":
            self._json(200, {"status": "ok"})
            return
        if self.path == "/jobs":
            self._json(200, st["jobs"])
            return
        if self.path.startswith("/jobs/"):
            jid = self.path.split("/jobs/", 1)[1]
            if jid == "j_wait":                 # running -> done
                st["polls"] += 1
                done = st["polls"] >= 2
                self._json(200, {
                    "job": jid, "status": "done" if done else "running",
                    "stage": "llm", "progress": 1.0 if done else 0.4,
                    "task": "simulate scenario",
                    "result": "simulation complete"})
                return
            if jid == "j_stuck":                # never terminal (timeout)
                self._json(200, {"job": jid, "status": "running",
                                 "stage": "llm", "progress": 0.1,
                                 "task": "long sim"})
                return
            if jid == "j_fail":
                self._json(200, {"job": jid, "status": "failed",
                                 "stage": "llm", "error_code": "E_INTERNAL",
                                 "task": "boom"})
                return
            for j in st["jobs"]:
                if j["job"] == jid:
                    self._json(200, j)
                    return
            self._json(404, {"detail": "Job not found"})
            return
        self._json(404, {"detail": "nope"})


@pytest.fixture
def brain(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Brain)
    server.state = {
        "jobs": [{"job": "j_active", "status": "running", "stage": "tool",
                  "progress": 0.3, "task": "open YouTube"}],
        "polls": 0,
    }
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def make_ctx(server=None, dead=False):
    cfg, _ = sup.load_config()
    cfg["paths"]["token_win"] = "unused"      # server skips auth here
    port = 1 if dead else server.server_address[1]
    cfg["supervisor"]["health_url"] = "http://127.0.0.1:%d/health" % port
    ctx = cli.Ctx(cfg)
    ctx.poll_tries, ctx.poll_delay = 2, 0.05
    return ctx


def parse(argv):
    return cli.build_parser().parse_args(argv)


SAMPLE_TIER = """# evolution-persona lane fragment
persona:
  # great_sage | raphael | ciel
  tier: great_sage

evolution:
  budget:
    max_tokens_tier: free
"""


def _tmp_tier(tmp_path, content=SAMPLE_TIER):
    p = tmp_path / "evolution-persona.yaml"
    p.write_text(content, encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# tier file surgery (fail-closed)
# --------------------------------------------------------------------------
def test_tier_read_write_surgical(tmp_path):
    p = _tmp_tier(tmp_path)
    assert cli._read_tier(p) == "great_sage"
    ok, detail = cli._write_tier("ciel", path=p)
    assert ok, detail
    text = p.read_text(encoding="utf-8")
    assert "tier: ciel" in text
    assert "max_tokens_tier: free" in text        # untouched
    assert "# great_sage | raphael | ciel" in text  # comments preserved
    assert cli._read_tier(p) == "ciel"


def test_tier_write_refuses_ambiguous_file(tmp_path):
    p = _tmp_tier(tmp_path, "persona:\n  tier: raphael\nother:\n  tier: ciel\n")
    ok, detail = cli._write_tier("great_sage", path=p)
    assert not ok and "EXACTLY one" in detail
    assert "tier: raphael" in p.read_text()       # nothing written


def test_tier_show_and_invalid_set_fail_closed(tmp_path, brain, capsys,
                                               monkeypatch):
    monkeypatch.setattr(cli, "TIER_FILE", _tmp_tier(tmp_path))
    ctx = make_ctx(brain)
    assert cli.cmd_tier(ctx, parse(["tier"])) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "persona tier: great_sage" in out and "brain running" in out
    # defense-in-depth: even bypassing argparse choices, unknown tier fails
    args = parse(["tier"])
    args.name = "GOD"                           # C1: never accepted
    assert cli.cmd_tier(ctx, args) == cli.EXIT_FAIL
    assert cli._read_tier(cli.TIER_FILE) == "great_sage"   # file untouched


# --------------------------------------------------------------------------
# tier set: guards + safe single-spawner recycle
# --------------------------------------------------------------------------
def test_tier_set_refused_with_active_jobs(tmp_path, brain, capsys,
                                           monkeypatch):
    monkeypatch.setattr(cli, "TIER_FILE", _tmp_tier(tmp_path))
    monkeypatch.setattr(sup, "stop_brain",
                        lambda c, l: pytest.fail("must not recycle"))
    ctx = make_ctx(brain)
    rc = cli.cmd_tier(ctx, parse(["tier", "raphael"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_FAIL
    assert "REFUSED: 1 active job" in out and "j_active" in out
    assert cli._read_tier(cli.TIER_FILE) == "great_sage"   # not written


def test_tier_set_force_recycles_single_spawner(tmp_path, brain, capsys,
                                                monkeypatch):
    monkeypatch.setattr(cli, "TIER_FILE", _tmp_tier(tmp_path))
    killed, spawned = [], []
    monkeypatch.setattr(sup, "stop_brain",
                        lambda c, l: killed.append(True) or True)
    monkeypatch.setattr(cli, "_spawn_brain_local",
                        lambda c: spawned.append(True) or True)
    monkeypatch.setattr(cli, "_pid_exists", lambda p: False)  # no supervisor
    ctx = make_ctx(brain)
    rc = cli.cmd_tier(ctx, parse(["tier", "raphael", "--force"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "WARNING: --force with 1 active job" in out
    assert cli._read_tier(cli.TIER_FILE) == "raphael"
    assert killed and spawned                    # recycle happened ONCE each
    assert "healthy" in out


def test_tier_set_when_brain_down_writes_and_defers(tmp_path, capsys,
                                                    monkeypatch):
    monkeypatch.setattr(cli, "TIER_FILE", _tmp_tier(tmp_path))
    monkeypatch.setattr(sup, "stop_brain",
                        lambda c, l: pytest.fail("no recycle when down"))
    ctx = make_ctx(dead=True)
    rc = cli.cmd_tier(ctx, parse(["tier", "ciel"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "applied at the next start" in out
    assert cli._read_tier(cli.TIER_FILE) == "ciel"


def test_tier_set_noop_when_already_set(tmp_path, brain, capsys,
                                        monkeypatch):
    monkeypatch.setattr(cli, "TIER_FILE", _tmp_tier(tmp_path))
    ctx = make_ctx(brain)
    rc = cli.cmd_tier(ctx, parse(["tier", "great_sage"]))
    assert rc == cli.EXIT_OK
    assert "already great_sage" in capsys.readouterr().out


# --------------------------------------------------------------------------
# jobs --wait (simulation supervision)
# --------------------------------------------------------------------------
def test_jobs_wait_until_done(brain, capsys):
    ctx = make_ctx(brain)
    rc = cli.cmd_jobs(ctx, parse(["jobs", "j_wait", "--wait",
                                  "--timeout", "10"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "running" in out and "job j_wait: done" in out
    assert "simulation complete" in out


def test_jobs_wait_failed_job_exits_nonzero(brain, capsys):
    ctx = make_ctx(brain)
    rc = cli.cmd_jobs(ctx, parse(["jobs", "j_fail", "--wait",
                                  "--timeout", "10"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_FAIL
    assert "job j_fail: failed" in out and "E_INTERNAL" in out


def test_jobs_wait_timeout_and_down(brain, capsys):
    ctx = make_ctx(brain)
    rc = cli.cmd_jobs(ctx, parse(["jobs", "j_stuck", "--wait",
                                  "--timeout", "1"]))
    assert rc == cli.EXIT_FAIL
    assert "timeout after" in capsys.readouterr().out
    # brain vanishing mid-wait = EXIT_DOWN
    dead = make_ctx(dead=True)
    rc = cli.cmd_jobs(dead, parse(["jobs", "j_wait", "--wait",
                                   "--timeout", "5"]))
    assert rc == cli.EXIT_DOWN
    assert "unreachable" in capsys.readouterr().out


# --------------------------------------------------------------------------
# shadow-instance readiness (port 8911, carried from the wave-4 gate record)
# --------------------------------------------------------------------------
def test_shadow_instance_8911_ready(monkeypatch):
    # explicit port for an instance without a §d row yet -> fully derived,
    # collision-free (helper backend 9911 never shadows another lane)
    monkeypatch.setenv("RAPHAEL_INSTANCE", "shadow")
    monkeypatch.setenv("RAPHAEL_PORT", "8911")
    cfg, note = sup.load_config()
    assert cfg["paths"]["brain_port"] == 8911
    assert cfg["supervisor"]["health_url"] == "http://127.0.0.1:8911/health"
    assert im.mutex_name() == "Raphael_Supervisor_shadow"
    assert im.body_lock_name() == "raphael_body_shadow.lock"
    assert im.relay_backend_port(8911) == 9911
    assert im.supervisor_pidfile().name == "supervisor_shadow.pid"
    # and WITHOUT the explicit port it must fail closed (never hit 8765)
    monkeypatch.delenv("RAPHAEL_PORT")
    with pytest.raises(ValueError, match="unknown RAPHAEL_INSTANCE"):
        sup.load_config()
