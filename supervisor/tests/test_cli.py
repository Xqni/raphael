"""raphael CLI tests — mock brain REST server (stdlib http.server), no real
stack, no real kills. Covers: status/auth/down paths, control actions, typed
input (say), jobs/cancel, logs tail, start/stop lifecycle via stubs."""
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
# Mock brain
# --------------------------------------------------------------------------
class _Brain(BaseHTTPRequestHandler):
    def log_message(self, *args):                      # silence
        pass

    def _json(self, code, obj):
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authed(self):
        return self.headers.get("X-Raphael-Token") == self.server.state[
            "token"]

    # -- GET ---------------------------------------------------------------
    def do_GET(self):
        st = self.server.state
        if not self._authed():
            self._json(401, {"detail": "Invalid token"})
            return
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        elif self.path == "/status":
            self._json(200, {"ok": True, "server_v": "test",
                             "mode": st.get("mode", "normal"),
                             "sessions": {"cli": 1}, "jobs_active": 0,
                             "paused": False})
        elif self.path == "/jobs":
            self._json(200, st["jobs"])
        elif self.path.startswith("/jobs/"):
            jid = self.path.split("/jobs/", 1)[1]
            job = next((j for j in st["jobs"] if j["job"] == jid), None)
            if job is None:
                self._json(404, {"detail": "Job not found"})
            else:
                self._json(200, job)
        else:
            self._json(404, {"detail": "nope"})

    # -- POST --------------------------------------------------------------
    def do_POST(self):
        st = self.server.state
        if not self._authed():
            self._json(401, {"detail": "Invalid token"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            body = json.loads(raw) if raw.strip() else {}
        except ValueError:
            body = {}
        st["posts"].append((self.path, body))
        if self.path == "/control":
            action = body.get("action", "")
            resp = {"ok": True, "action": action,
                    "mode": "private" if "private" in action else "normal",
                    "persisted": bool(body.get("persist", True))}
            if action in ("pause", "resume"):
                resp["paused"] = action == "pause"
            if action in ("private_on", "private_off"):
                resp["mode"] = "private" if action == "private_on" \
                    else "normal"
            self._json(200, resp)
        elif self.path == "/jobs":
            self._json(200, {"job_id": "j_20261006_0001",
                             "job": {"job": "j_20261006_0001",
                                     "status": "queued"}})
        elif self.path.endswith("/cancel"):
            self._json(200, {"cancelled": True,
                             "job": {"status": "cancelled"}})
        else:
            self._json(404, {"detail": "nope"})


@pytest.fixture
def brain(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("unit-test-token")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Brain)
    server.state = {"token": "unit-test-token",
                    "jobs": [{"job": "j_1", "status": "running",
                              "stage": "llm", "progress": 0.5,
                              "task": "open YouTube and search lo-fi"}],
                    "posts": [], "mode": "normal"}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def make_ctx(server, token_file=None, dead=False):
    cfg, _ = sup.load_config()
    if token_file is not None:
        cfg["paths"]["token_win"] = str(token_file)
    port = 1 if dead else server.server_address[1]
    cfg["supervisor"]["health_url"] = "http://127.0.0.1:%d/health" % port
    ctx = cli.Ctx(cfg)
    ctx.poll_tries = 1
    ctx.poll_delay = 0.01
    return ctx


def parse(argv):
    return cli.build_parser().parse_args(argv)


# --------------------------------------------------------------------------
# status / auth / down
# --------------------------------------------------------------------------
def test_status_ok(brain, tmp_path, capsys):
    ctx = make_ctx(brain, tmp_path / "token")
    rc = cli.cmd_status(ctx, parse(["status"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "brain: ok @ http://127.0.0.1:%d" % brain.server_address[1] in out
    assert "mode" in out and "normal" in out
    assert "unit-test-token" not in out          # value never printed


def test_status_token_rejected(brain, tmp_path, capsys):
    wrong = tmp_path / "wrong"
    wrong.write_text("not-the-right-token")
    ctx = make_ctx(brain, wrong)
    rc = cli.cmd_status(ctx, parse(["status"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_FAIL
    assert "TOKEN REJECTED" in out
    assert "not-the-right-token" not in out      # value never printed


def test_status_down(brain, capsys):
    ctx = make_ctx(brain, dead=True)
    rc = cli.cmd_status(ctx, parse(["status"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_DOWN
    assert "unreachable" in out and "raphael start" in out


# --------------------------------------------------------------------------
# control: pause / resume / private
# --------------------------------------------------------------------------
@pytest.mark.parametrize("argv,expect_action", [
    (["pause"], "pause"),
    (["resume"], "resume"),
    (["private", "on"], "private_on"),
    (["private", "off"], "private_off"),
])
def test_control_actions(brain, tmp_path, capsys, argv, expect_action):
    ctx = make_ctx(brain, tmp_path / "token")
    handler = cli.HANDLERS[argv[0]]
    rc = handler(ctx, parse(argv))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    posts = brain.state["posts"]
    assert posts[-1][0] == "/control"
    assert posts[-1][1] == {"action": expect_action, "persist": True}
    assert expect_action in out


# --------------------------------------------------------------------------
# say / jobs / cancel
# --------------------------------------------------------------------------
def test_say_typed_input(brain, tmp_path, capsys):
    ctx = make_ctx(brain, tmp_path / "token")
    rc = cli.cmd_say(ctx, parse(["say", "what", "am", "I", "looking", "at"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    path, body = brain.state["posts"][-1]
    assert path == "/jobs"
    assert body["text"] == "what am I looking at"
    assert body["source"] == "text"
    assert body["input_lock"] is False
    assert "j_20261006_0001" in out and "queued" in out


def test_say_gui_takes_input_lock(brain, tmp_path):
    ctx = make_ctx(brain, tmp_path / "token")
    rc = cli.cmd_say(ctx, parse(["say", "click", "the", "blue", "button",
                                 "--gui"]))
    assert rc == cli.EXIT_OK
    assert brain.state["posts"][-1][1]["input_lock"] is True


def test_jobs_list_and_detail(brain, tmp_path, capsys):
    ctx = make_ctx(brain, tmp_path / "token")
    rc = cli.cmd_jobs(ctx, parse(["jobs"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "j_1" in out and "running" in out and "lo-fi" in out
    rc = cli.cmd_jobs(ctx, parse(["jobs", "j_1"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert '"status": "running"' in out
    rc = cli.cmd_jobs(ctx, parse(["jobs", "j_missing"]))
    assert rc == cli.EXIT_FAIL                   # server 404


def test_cancel_gui_scope(brain, tmp_path, capsys):
    ctx = make_ctx(brain, tmp_path / "token")
    rc = cli.cmd_cancel(ctx, parse(["cancel", "j_1", "--gui"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    path, body = brain.state["posts"][-1]
    assert path == "/jobs/j_1/cancel"
    assert body == {"scope": "gui"}
    assert "scope=gui" in out


# --------------------------------------------------------------------------
# logs
# --------------------------------------------------------------------------
def test_logs_tail(brain, tmp_path, capsys, monkeypatch):
    logf = tmp_path / "supervisor.log"
    logf.write_text("".join("line %d\n" % i for i in range(100)))
    monkeypatch.setattr(im, "log_path",
                        lambda name, inst=None, root=None: logf)
    ctx = make_ctx(brain, tmp_path / "token")
    rc = cli.cmd_logs(ctx, parse(["logs", "-n", "5"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "line 99" in out and "line 95" in out   # last 5 of 0..99
    assert "line 94" not in out                    # window respected


def test_logs_missing_file(brain, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(im, "log_path",
                        lambda name, inst=None, root=None:
                        tmp_path / "absent.log")
    ctx = make_ctx(brain, tmp_path / "token")
    assert cli.cmd_logs(ctx, parse(["logs"])) == cli.EXIT_FAIL


# --------------------------------------------------------------------------
# start / stop (stubbed lifecycle — never spawns or kills for real)
# --------------------------------------------------------------------------
def test_start_already_running(brain, tmp_path, capsys, monkeypatch):
    ctx = make_ctx(brain, tmp_path / "token")
    monkeypatch.setattr(cli, "_spawn_brain_local",
                        lambda c: pytest.fail("must not spawn when up"))
    monkeypatch.setattr(cli, "_spawn_supervisor",
                        lambda c: pytest.fail("must not spawn when up"))
    rc = cli.cmd_start(ctx, parse(["start"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "already running" in out


def test_start_spawn_then_still_down_is_exit_down(tmp_path, capsys,
                                                  monkeypatch):
    ctx = make_ctx(None, tmp_path / "token", dead=True)
    spawned = []
    monkeypatch.setattr(cli, "_spawn_brain_local",
                        lambda c: spawned.append(c.instance) or True)
    monkeypatch.setattr(cli, "_spawn_supervisor",
                        lambda c: pytest.fail("non-Windows must not use "
                                              "supervisor path"))
    rc = cli.cmd_start(ctx, parse(["start"]))
    out = capsys.readouterr().out
    assert spawned                                # local spawn attempted
    assert rc == cli.EXIT_DOWN
    assert "not healthy" in out


def test_stop_idempotent_when_everything_down(brain, capsys, monkeypatch,
                                              tmp_path):
    monkeypatch.setattr(im, "supervisor_pidfile",
                        lambda inst=None, root=None: tmp_path / "nope.pid")
    stopped = []
    monkeypatch.setattr(sup, "stop_brain",
                        lambda cfg, log: stopped.append(True) or False)
    ctx = make_ctx(brain, dead=True)             # endpoint refused
    rc = cli.cmd_stop(ctx, parse(["stop"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "nothing running" in out
    assert stopped                                # brain probe was attempted


def test_stop_reports_brain_kill(capsys, monkeypatch, tmp_path, brain):
    monkeypatch.setattr(im, "supervisor_pidfile",
                        lambda inst=None, root=None: tmp_path / "nope.pid")
    monkeypatch.setattr(sup, "stop_brain",
                        lambda cfg, log: True)    # pretend kill issued
    ctx = make_ctx(brain, dead=True)
    rc = cli.cmd_stop(ctx, parse(["stop"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "brain stopped (pidfile + cmdline verified)" in out


def test_stop_fails_if_brain_survives(brain, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(im, "supervisor_pidfile",
                        lambda inst=None, root=None: tmp_path / "nope.pid")
    monkeypatch.setattr(sup, "stop_brain", lambda cfg, log: True)
    ctx = make_ctx(brain, tmp_path / "token")    # endpoint STILL answers
    rc = cli.cmd_stop(ctx, parse(["stop"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_FAIL
    assert "still answering" in out


# --------------------------------------------------------------------------
# dispatch + selftest wiring
# --------------------------------------------------------------------------
def test_main_dispatch_loads_config_and_runs(brain, tmp_path, monkeypatch,
                                             capsys):
    cfg, _ = sup.load_config()
    cfg["paths"]["token_win"] = str(tmp_path / "token")
    cfg["supervisor"]["health_url"] = "http://127.0.0.1:%d/health" % \
        brain.server_address[1]
    monkeypatch.setattr(sup, "load_config", lambda path=None: (cfg, "test"))
    rc = cli.main(["status"])
    assert rc == cli.EXIT_OK
    assert "brain: ok" in capsys.readouterr().out


def test_selftest_runs_supervisor_selfcheck(tmp_path, monkeypatch, capsys):
    ctx = make_ctx(None, tmp_path / "token", dead=True)
    rc = cli.cmd_selftest(ctx, parse(["selftest"]))
    out = capsys.readouterr().out
    # supervisor selfcheck writes its report on the inherited stdout (users
    # see it live); only the CLI banner lands in capsys — exit code is the
    # contract (0 = no FAIL rows).
    assert rc == 0, out
    assert "raphael CLI: instance=main" in out
