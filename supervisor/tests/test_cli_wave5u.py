"""Wave 5U §5.7 CLI: one-command start dry-run, confirm (WS), tasks,
chat (answer frames), latency — mock REST + mock WS servers, zero spawns."""
import base64
import importlib.util
import json
import socket
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from supervisor import main as sup

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "raphael_cli_under_test", _ROOT / "scripts" / "raphael_cli.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

_GUID = "258EAFA5-E914-47DA-95CA-5AB0DC85B11F"


def parse(argv):
    return cli.build_parser().parse_args(argv)


# --------------------------------------------------------------------------
# REST mock (health/status/jobs/cancel)
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
        elif self.path == "/status":
            self._json(200, st["status"])
        elif self.path == "/jobs":
            self._json(200, st["jobs"])
        elif self.path == "/jobs/j_2":
            self._json(200, {"job": "j_2", "status": "running",
                             "stage": "llm", "progress": 0.5,
                             "task": "research mini-PC"})
        else:
            self._json(404, {"detail": "nope"})

    def do_POST(self):
        st = self.server.state
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.state["posts"].append((self.path, body))
        if self.path == "/jobs/j_2/cancel":
            self._json(200, {"cancelled": True,
                             "job": {"status": "cancelled"}})
        else:
            self._json(404, {"detail": "nope"})


@pytest.fixture
def brain(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Brain)
    server.state = {
        "status": {"ok": True, "server_v": "test", "mode": "normal",
                   "sessions": {"cli": 1}, "jobs_active": 1,
                   "latency": {"stages": {"llm": 1.2, "tts_first": 0.9},
                               "hist": {"llm": {"count": 9, "p50": 1.1,
                                                "p95": 2.2, "max": 3.0},
                                        "tts_first": {"count": 4, "p50": 0.8,
                                                      "p95": 1.4, "max": 1.6}},
                               "job": "j_1"}},
        "jobs": [{"job": "j_2", "status": "running", "stage": "llm",
                  "progress": 0.5, "task": "research mini-PC"}],
        "posts": [],
    }
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def make_ctx(server=None, dead=False, default_port=False):
    cfg, _ = sup.load_config()
    if default_port:
        port = None                              # keep config's 8765
    elif server:
        port = server.server_address[1]
    else:
        port = 1                                 # dead endpoint
    if port is not None:
        cfg["supervisor"]["health_url"] = "http://127.0.0.1:%d/health" % port
    ctx = cli.Ctx(cfg)
    ctx.poll_tries, ctx.poll_delay = 2, 0.05
    return ctx


# --------------------------------------------------------------------------
# one-command start: dry-run (acceptance: lists components, exit 0)
# --------------------------------------------------------------------------
def test_start_dry_run_lists_components_and_spawns_nothing(capsys,
                                                           monkeypatch):
    monkeypatch.setattr(cli, "_spawn_supervisor",
                        lambda c: pytest.fail("dry-run must not spawn"))
    monkeypatch.setattr(cli, "_spawn_brain_local",
                        lambda c: pytest.fail("dry-run must not spawn"))
    ctx = make_ctx(default_port=True)
    rc = cli.cmd_start(ctx, parse(["start", "--dry-run"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    for component in ("supervisor:", "brain:", "body:", "orb:", "relay:",
                      "TTS:"):
        assert component in out, component
    assert "chat:  http://127.0.0.1:8765/chat" in out
    assert "nothing spawned" in out


def test_status_prints_chat_url(brain, capsys):
    ctx = make_ctx(brain)
    rc = cli.cmd_status(ctx, parse(["status"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "chat:  http://127.0.0.1:%d/chat" % brain.server_address[1] in out


# --------------------------------------------------------------------------
# latency (value-blind numbers only)
# --------------------------------------------------------------------------
def test_latency_prints_p50_p95_table(brain, capsys):
    ctx = make_ctx(brain)
    rc = cli.cmd_latency(ctx, parse(["latency"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "p50" in out and "p95" in out
    assert "llm" in out and "tts_first" in out
    assert "1.1" in out and "2.2" in out          # p50/p95 numbers
    assert "sampled during job: j_1" in out


def test_latency_handles_missing_data(brain, capsys, monkeypatch):
    ctx = make_ctx(brain)
    ctx2 = make_ctx(dead=True)                    # unreachable
    rc = cli.cmd_latency(ctx2, parse(["latency"]))
    assert rc == cli.EXIT_DOWN
    # reachable but no latency key
    st = brain.state["status"]
    saved = st.pop("latency")
    try:
        rc = cli.cmd_latency(ctx, parse(["latency"]))
        assert rc == cli.EXIT_OK
        assert "no data" in capsys.readouterr().out
    finally:
        st["latency"] = saved


# --------------------------------------------------------------------------
# tasks alias
# --------------------------------------------------------------------------
def test_tasks_list_show_cancel(brain, capsys):
    ctx = make_ctx(brain)
    rc = cli.cmd_tasks(ctx, parse(["tasks"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK and "j_2" in out and "research mini-PC" in out
    rc = cli.cmd_tasks(ctx, parse(["tasks", "j_2"]))
    assert rc == cli.EXIT_OK and "j_2" in capsys.readouterr().out
    rc = cli.cmd_tasks(ctx, parse(["tasks", "j_2", "--cancel"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK and "cancelled" in out
    assert brain.state["posts"][-1] == ("/jobs/j_2/cancel",
                                               {"scope": "full"})
    rc = cli.cmd_tasks(ctx, parse(["tasks", "--cancel"]))
    assert rc == cli.EXIT_FAIL                    # --cancel without id


# --------------------------------------------------------------------------
# mock WebSocket brain (handshake + frames) for confirm/chat
# --------------------------------------------------------------------------
def _srv_send(sock, obj):
    payload = json.dumps(obj).encode("utf-8")
    ln = len(payload)
    if ln < 126:
        head = bytes([0x81, ln])
    elif ln < 65536:
        head = bytes([0x81, 126]) + struct.pack("!H", ln)
    else:
        head = bytes([0x81, 127]) + struct.pack("!Q", ln)
    sock.sendall(head + payload)


def _srv_recv(sock):
    def exact(n):
        out = b""
        while len(out) < n:
            chunk = sock.recv(n - len(out))
            if not chunk:
                raise OSError("closed")
            out += chunk
        return out
    b0, b1 = exact(2)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F
    if length == 126:
        length = struct.unpack("!H", exact(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", exact(8))[0]
    mask = exact(4) if masked else None
    payload = exact(length) if length else b""
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def _start_ws_brain(state):
    """Handshake + scripted frame handling -> (port, sock_queue_for_stop)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    port = srv.getsockname()[1]
    ready = threading.Event()

    def serve():
        ready.set()
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        try:
            # handshake
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                buf += chunk
            headers = buf.split(b"\r\n\r\n", 1)[0].decode("latin-1")
            key = ""
            for line in headers.split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
            accept = base64.b64encode(
                __import__("hashlib").sha1(
                    (key + _GUID).encode()).digest()).decode()
            conn.sendall((
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode())
            # frame loop
            for _ in range(20):
                opcode, payload = _srv_recv(conn)
                if opcode != 0x1:
                    if opcode == 0x8:
                        return
                    continue
                msg = json.loads(payload.decode())
                state["frames"].append(msg)
                if msg.get("type") == "auth":
                    if msg.get("token") == state["token"]:
                        _srv_send(conn, {"type": "auth_ok", "v": 1,
                                         "session": "s1", "server_v": "t"})
                    else:
                        _srv_send(conn, {"type": "auth_fail", "v": 1,
                                         "code": "E_AUTH"})
                elif msg.get("type") == "confirm_resp":
                    _srv_send(conn, {"type": "ack", "v": 1,
                                     "job": msg.get("job"),
                                     "answer": msg.get("answer"),
                                     "accepted": True})
                elif msg.get("type") == "command":
                    _srv_send(conn, {"type": "ack", "v": 1,
                                     "job": "j_99"})
                    _srv_send(conn, {"type": "job_event", "v": 1,
                                     "job": "j_99", "status": "running",
                                     "stage": "llm"})
                    _srv_send(conn, {"type": "answer", "v": 1,
                                     "job": "j_99",
                                     "text": "Raphael says hi back.",
                                     "format": "answer"})
        finally:
            for _s in (conn, srv):
                try:
                    _s.close()
                except OSError:
                    pass

    threading.Thread(target=serve, daemon=True).start()
    ready.wait(timeout=5)
    return port


@pytest.fixture
def ws_brain(tmp_path):
    resolved = sup.resolve_token(sup.load_config()[0])[1] or "unit-test-token"
    state = {"token": resolved, "frames": []}
    port = _start_ws_brain(state)
    yield state, port


def _ws_ctx(port):
    cfg, _ = sup.load_config()
    cfg["supervisor"]["health_url"] = "http://127.0.0.1:%d/health" % port
    ctx = cli.Ctx(cfg)
    return ctx


# --------------------------------------------------------------------------
# confirm — WS confirm_resp as role cli -> ack
# --------------------------------------------------------------------------
def test_confirm_sends_exact_frame_and_prints_result(ws_brain, capsys):
    state, port = ws_brain
    ctx = _ws_ctx(port)
    rc = cli.cmd_confirm(ctx, parse(["confirm", "j_42", "yes"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "confirmed j_42" in out and "accepted" in out
    sent = [f for f in state["frames"] if f.get("type") == "confirm_resp"]
    assert len(sent) == 1
    frame = sent[0]
    # exact contract shape (PROTOCOL §3): type/job/answer + envelope
    assert frame["type"] == "confirm_resp" and frame["job"] == "j_42"
    assert frame["answer"] == "yes"
    assert frame["v"] == 1 and "seq" in frame


def test_confirm_auth_failure_is_value_blind(ws_brain, capsys):
    state, port = ws_brain
    state["token"] = "rotated-token"             # ctx still has old token
    ctx = _ws_ctx(port)
    rc = cli.cmd_confirm(ctx, parse(["confirm", "j_1", "no"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_DOWN
    assert "auth failed" in out
    assert "unit-test-token" not in out           # never leaks the token


# --------------------------------------------------------------------------
# chat — prints answer frames from the command round trip
# --------------------------------------------------------------------------
def test_chat_prints_answer_frames(ws_brain, capsys, monkeypatch):
    state, port = ws_brain
    ctx = _ws_ctx(port)
    inputs = iter(["open youtube", "exit"])

    def fake_input(_prompt=""):
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    rc = cli.cmd_chat(ctx, parse(["chat"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert "Raphael says hi back." in out         # the answer frame text
    assert "connected as role=cli" in out
    cmds = [f for f in state["frames"] if f.get("type") == "command"]
    assert len(cmds) == 1
    assert cmds[0]["text"] == "open youtube" and cmds[0]["source"] == "text"
    assert cmds[0]["v"] == 1 and "seq" in cmds[0]


def test_chat_web_prints_url_and_opens(ws_brain, capsys, monkeypatch):
    state, port = ws_brain
    ctx = _ws_ctx(port)
    opened = {}
    monkeypatch.setattr(cli, "_open_browser",
                        lambda u: opened.setdefault("url", u) or True)
    rc = cli.cmd_chat(ctx, parse(["chat", "--web"]))
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK
    assert opened.get("url", "").endswith("/chat")
    assert "chat web UI: http://127.0.0.1:%d/chat" % port in out
