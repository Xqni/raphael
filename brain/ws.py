"""WebSocket hub — the REAL /ws endpoint (PROTOCOL §1–§4, §6).

Responsibilities:
- auth handshake within 5 s (token via hmac.compare_digest, constant-time);
  upgrade-time token check as defense in depth; ≥5 failed auths/IP in 60 s
  → refuse new handshakes 5 min (E_AUTH_RATE);
- role negotiation ui|body|cli + capability enforcement (§4) — exceeding a
  role's capabilities → E_UNSUPPORTED warning frame, never trusted claims;
- ping/pong keepalive: server-initiated app-level ping every 10 s (uvicorn
  does not auto-ping; this is the ONLY ping source), 3 missed pongs → close
  and cancel that session's tasks (PROTOCOL §1);
- canonical message shapes: auth, command, confirm_resp, cancel, control,
  state_req, job_list/job_get, act_res, orb_input + Brain→Client
  auth_ok/auth_fail, ack, job_event, needs_confirm, orb_state, subtitle,
  speak, error, pong;
- limits: 8 MiB max message, 40 text msgs/s per connection (125/s binary
  audio frames) → E_RATE_LIMIT close;
- narration fanout: job_event to all roles, orb_state/subtitle to the orb
  (role=ui), speak to role=body only.
"""
import asyncio
import hmac
import json
import os
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, Optional, Set

from starlette.websockets import WebSocket, WebSocketDisconnect

from .auth import bearer_from_header, check_token, get_token
from .control import apply_control
from .jobs import store
from .mode import get_mode

SERVER_V = 'brain-0.2.0'
ROLES = {'ui', 'body', 'cli'}

# Capability tables (PROTOCOL §4)
CAN_SEND_COMMAND = {'ui', 'body', 'cli'}
CAN_SEND_AUDIO = {'body'}
CAN_SEND_CONFIRM_RESP = {'ui', 'body', 'cli'}
CAN_SEND_CONTROL = {'ui', 'body', 'cli'}
CAN_SEND_ACT_RES = {'body'}
CAN_SEND_ORB_INPUT = {'ui'}
CAN_SEND_STATE_REQ = {'ui', 'cli'}
CAN_SEND_JOB_QUERY = {'ui', 'body', 'cli'}
CAN_SEND_CANCEL = {'ui', 'body', 'cli'}

KNOWN_CLIENT_TYPES = {
    'command', 'audio_start', 'audio_end', 'confirm_resp', 'control', 'act_res',
    'orb_input', 'state_req', 'job_list', 'job_get', 'cancel', 'pong', 'auth',
}

MAX_MSG = 8 * 1024 * 1024          # §1: 8 MiB
RATE_TEXT = 40                      # §1: 40 msgs/s per connection
RATE_BINARY = 125                   # §1: binary audio frames exempt at 125/s
AUTH_DEADLINE_S = 5.0               # §2: auth frame within 5 s
PING_MISS_LIMIT = 3                 # §1: 3 missed pongs -> close (~30 s silence)
AUTH_FAIL_WINDOW_S = 60.0
AUTH_FAIL_MAX = 5
AUTH_FAIL_BAN_S = 300.0
MAX_STRIKES = 3                     # repeated malformed frames -> close


def _clear_yes_no(text: str) -> Optional[str]:
    """'yes' | 'no' when the text clearly IS an answer, else None (used by the
    voice-confirm interception: unclear speech never resolves a confirmation)."""
    from .confirm import NO_WORDS, YES_WORDS
    a = (text or '').strip().lower().strip('.,!?')
    words = a.split()
    first = words[0] if words else ''
    if a in YES_WORDS or first in YES_WORDS:
        return 'yes'
    if a in NO_WORDS or first in NO_WORDS:
        return 'no'
    return None


class Session:
    # audio_buf/audio_reason were added by the mic lane WITHOUT extending
    # __slots__ -> every audio_start died with AttributeError (found by the
    # synthetic mic-lane E2E).
    __slots__ = ('sid', 'ws', 'ip', 'role', 'client', 'client_v', 'authed',
                 'missed', 'rate', 'created', 'jobs', 'strikes', 'bin_rate',
                 'audio_buf', 'audio_reason')

    def __init__(self, ws: WebSocket, ip: str):
        self.sid = uuid.uuid4().hex[:12]
        self.ws = ws
        self.ip = ip
        self.role: Optional[str] = None
        self.client: Optional[str] = None
        self.client_v: Optional[str] = None
        self.authed = False
        self.missed = 0
        self.rate: Deque[float] = deque()
        self.bin_rate: Deque[float] = deque()
        self.created = time.time()
        self.jobs: Set[int] = set()
        self.strikes = 0
        self.audio_buf = bytearray()
        self.audio_reason = 'wake'


class WsHub:
    def __init__(self):
        self._sessions: Dict[str, Session] = {}
        self._auth_fails: Dict[str, Deque[float]] = {}
        self._banned_until: Dict[str, float] = {}
        self._ping_task: Optional[asyncio.Task] = None
        self.engine = None  # wired by brain.app lifespan

    # ---- lifecycle ---------------------------------------------------------
    @staticmethod
    def ping_interval() -> float:
        try:
            return float(os.environ.get('RAPHAEL_WS_PING_INTERVAL_S', '10'))
        except ValueError:
            return 10.0

    async def start(self):
        if self._ping_task is None:
            self._ping_task = asyncio.create_task(self._ping_loop(), name='ws-ping')

    async def stop(self):
        if self._ping_task is not None:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            self._ping_task = None
        for s in list(self._sessions.values()):
            await self._safe_close(s)
        self._sessions.clear()

    async def _ping_loop(self):
        while True:
            await asyncio.sleep(self.ping_interval())
            await self.ping_once()

    async def ping_once(self):
        for s in list(self._sessions.values()):
            if not s.authed:
                continue
            if s.missed >= PING_MISS_LIMIT:
                await self._safe_close(s)
                continue
            s.missed += 1
            await self._send(s, {'type': 'ping', 'v': 1})

    # ---- connection handling ----------------------------------------------
    async def handle(self, ws: WebSocket):
        ip = ws.client.host if ws.client else 'unknown'
        s = Session(ws, ip)
        now = time.time()
        ban_until = self._banned_until.get(ip, 0.0)
        # defense in depth: a WRONG token on the upgrade is refused immediately
        up_token = (ws.headers.get('x-raphael-token')
                    or bearer_from_header(ws.headers.get('authorization'))
                    or ws.query_params.get('token'))
        expected = get_token()
        try:
            if now < ban_until:
                await ws.accept()
                await self._send(s, {'type': 'auth_fail', 'v': 1, 'code': 'E_AUTH_RATE'})
                await ws.close()
                return
            if up_token and expected and not hmac.compare_digest(up_token, expected):
                await ws.accept()
                await self._send(s, {'type': 'auth_fail', 'v': 1, 'code': 'E_AUTH'})
                await ws.close()
                return
        except Exception:  # noqa: BLE001
            return
        self._sessions[s.sid] = s
        auth_deadline = asyncio.create_task(self._auth_timeout(s), name=f'auth-{s.sid}')
        try:
            await ws.accept()
            while True:
                msg = await ws.receive()
                mtype = msg.get('type')
                if mtype == 'websocket.disconnect':
                    break
                if mtype == 'websocket.receive':
                    if msg.get('text') is not None:
                        await self._handle_text(s, msg['text'])
                    elif msg.get('bytes') is not None:
                        await self._handle_binary(s, msg['bytes'])
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001 — a bad connection must not kill the brain
            pass
        finally:
            auth_deadline.cancel()
            self._sessions.pop(s.sid, None)
            # PROTOCOL §1: on disconnect, cancel that session's tasks
            if self.engine is not None:
                try:
                    self.engine.cancel_session(s.sid)
                except Exception:  # noqa: BLE001
                    pass

    async def _auth_timeout(self, s: Session):
        await asyncio.sleep(AUTH_DEADLINE_S)
        if not s.authed:
            await self._send(s, {'type': 'auth_fail', 'v': 1, 'code': 'E_AUTH'})
            await self._safe_close(s)

    # ---- frame IO ----------------------------------------------------------
    async def _send(self, s: Session, obj: Dict[str, Any]):
        try:
            await s.ws.send_text(json.dumps(obj, ensure_ascii=False))
        except Exception:  # noqa: BLE001 — dead socket; disconnect path cleans up
            pass

    async def _safe_close(self, s: Session):
        try:
            await s.ws.close()
        except Exception:  # noqa: BLE001
            pass

    def session_counts(self) -> Dict[str, int]:
        """Authed sessions per role (surfaced on GET /status — observability
        gap found while verifying who was actually connected)."""
        counts: Dict[str, int] = {}
        for s in self._sessions.values():
            if s.authed and s.role:
                counts[s.role] = counts.get(s.role, 0) + 1
        return counts

    def broadcast(self, frame: Dict[str, Any], roles: Optional[Set[str]] = None,
                  exclude_sid: Optional[str] = None):
        """Fan out a control frame to authed sessions (sync-safe: schedules a task)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _run():
            for sess in list(self._sessions.values()):
                if not sess.authed:
                    continue
                if exclude_sid and sess.sid == exclude_sid:
                    continue
                if roles and sess.role not in roles:
                    continue
                await self._send(sess, frame)

        loop.create_task(_run())

    # ---- narration (loop.py entry point) -----------------------------------
    def narrate(self, job: str, text: str, state: Optional[str] = None):
        """Legacy narrate: only used if loop.py isn't handling speak.
        Now loop.py calls voice.speak directly via _async_narrate."""
        self.broadcast({'type': 'subtitle', 'v': 1, 'job': job,
                        'text': str(text)[:200], 'fade_ms': 4000})
        if state:
            self.refresh_orb_state()

    def refresh_orb_state(self):
        # INTERFACES §e: one frame builder (brain/orbstate.py) — this stays the
        # single entry point every caller already uses.
        from . import orbstate
        orbstate.refresh(hub=self, engine=self.engine)

    def get_body_session(self) -> Optional[Session]:
        """Returns the first authenticated session with role=body."""
        for s in self._sessions.values():
            if s.authed and s.role == 'body':
                return s
        return None

    async def _send_binary(self, s: Session, data: bytes):
        try:
            await s.ws.send_bytes(data)
        except Exception:  # noqa: BLE001
            pass

    def send_binary(self, s: Session, data: bytes):
        """Schedules a binary send to a specific session (sync-safe)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._send_binary(s, data))

    def broadcast_binary(self, data: bytes, roles: Optional[Set[str]] = None,
                         exclude_sid: Optional[str] = None):
        """Fan out binary data to authed sessions (sync-safe)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        
        async def _run():
            for sess in list(self._sessions.values()):
                if not sess.authed:
                    continue
                if exclude_sid and sess.sid == exclude_sid:
                    continue
                if roles and sess.role not in roles:
                    continue
                await self._send_binary(sess, data)
        
        loop.create_task(_run())

    # ---- dispatch ----------------------------------------------------------
    async def _handle_text(self, s: Session, raw: str):
        if len(raw) > MAX_MSG:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_BAD_MSG',
                                 'detail': 'message exceeds 8 MiB'})
            await self._safe_close(s)
            return
        now = time.time()
        while s.rate and now - s.rate[0] > 1.0:
            s.rate.popleft()
        if len(s.rate) >= RATE_TEXT:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_RATE_LIMIT',
                                 'detail': f'max {RATE_TEXT} msgs/s'})
            await self._safe_close(s)
            return
        s.rate.append(now)
        try:
            msg = json.loads(raw)
            if not isinstance(msg, dict):
                raise ValueError('frame is not an object')
        except (TypeError, ValueError):
            s.strikes += 1
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_BAD_MSG'})
            if s.strikes >= MAX_STRIKES:
                await self._safe_close(s)
            return
        await self._dispatch(s, msg)

    async def _handle_binary(self, s: Session, data: bytes):
        if not s.authed:
            await self._safe_close(s)
            return
        now = time.time()
        while s.bin_rate and now - s.bin_rate[0] > 1.0:
            s.bin_rate.popleft()
        if len(s.bin_rate) >= RATE_BINARY:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_RATE_LIMIT'})
            await self._safe_close(s)
            return
        s.bin_rate.append(now)
        # PROTOCOL §6: [4-byte magic "RAPH"][u8 kind][u32 seq][payload]
        if len(data) < 9 or data[:4] != b'RAPH':
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_BAD_MSG',
                                 'detail': 'bad binary framing'})
            await self._safe_close(s)
            return
        kind = data[4]
        if kind == 1 and s.role == 'body':
            # mic PCM chunk -> accumulate for the STT lane. (Was a bare `pass`
            # stub — the buffer never filled and audio_end always saw it
            # empty, so nothing was ever transcribed; found by the synthetic
            # mic-lane E2E.) 10 MB safety cap (~10 min of 16k mono s16le).
            if len(s.audio_buf) < 10 * 1024 * 1024:
                s.audio_buf += data[9:]
        elif kind == 2:
            pass  # TTS chunk (brain→body) — not produced yet
        else:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_UNSUPPORTED',
                                 'detail': f'binary kind {kind} for role {s.role}'})

    async def _dispatch(self, s: Session, msg: Dict[str, Any]):
        mtype = msg.get('type')
        if not isinstance(mtype, str):
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_BAD_MSG'})
            return
        if not s.authed:
            if mtype != 'auth':
                await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_PROTO',
                                     'detail': 'auth required'})
                await self._safe_close(s)
                return
            await self._handle_auth(s, msg)
            return
        if mtype == 'pong':
            s.missed = 0
            return
        if mtype == 'auth':
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_PROTO',
                                 'detail': 'already authenticated'})
            return
        caps = {
            'command': CAN_SEND_COMMAND,
            'audio_start': CAN_SEND_AUDIO,
            'audio_end': CAN_SEND_AUDIO,
            'confirm_resp': CAN_SEND_CONFIRM_RESP,
            'control': CAN_SEND_CONTROL,
            'act_res': CAN_SEND_ACT_RES,
            'orb_input': CAN_SEND_ORB_INPUT,
            'state_req': CAN_SEND_STATE_REQ,
            'job_list': CAN_SEND_JOB_QUERY,
            'job_get': CAN_SEND_JOB_QUERY,
            'cancel': CAN_SEND_CANCEL,
        }
        if mtype in caps and s.role not in caps[mtype]:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_UNSUPPORTED',
                                 'detail': f'{mtype} not allowed for role {s.role}'})
            return
        if mtype not in KNOWN_CLIENT_TYPES:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_UNSUPPORTED',
                                 'detail': f'unknown type {mtype}'})
            return
        handler = getattr(self, '_on_' + mtype, None)
        if handler is None:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_UNSUPPORTED',
                                 'detail': f'no handler for {mtype}'})
            return
        try:
            await handler(s, msg)
        except Exception as e:  # noqa: BLE001 — handler bugs must not kill the session
            import traceback
            print(f"[ws] handler '{mtype}' failed: {type(e).__name__}: {e}\n"
                  + traceback.format_exc(), flush=True)
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_INTERNAL',
                                 'detail': type(e).__name__})

    async def _handle_auth(self, s: Session, msg: Dict[str, Any]):
        if msg.get('v') != 1:
            await self._send(s, {'type': 'auth_fail', 'v': 1, 'code': 'E_PROTO'})
            await self._safe_close(s)
            return
        role = msg.get('role')
        if role not in ROLES:
            await self._send(s, {'type': 'auth_fail', 'v': 1, 'code': 'E_PROTO',
                                 'detail': 'role must be ui|body|cli'})
            await self._safe_close(s)
            return
        if not check_token(msg.get('token')):
            self._record_auth_fail(s.ip)
            await self._send(s, {'type': 'auth_fail', 'v': 1, 'code': 'E_AUTH'})
            await self._safe_close(s)
            return
        s.authed = True
        s.role = role
        s.client = msg.get('client')
        s.client_v = msg.get('client_v')
        await self._send(s, {'type': 'auth_ok', 'v': 1, 'session': s.sid,
                             'server_v': SERVER_V})
        await self._send(s, {'type': 'ping', 'v': 1})  # kick off keepalive
        self.refresh_orb_state()

    def _record_auth_fail(self, ip: str):
        now = time.time()
        dq = self._auth_fails.setdefault(ip, deque())
        dq.append(now)
        while dq and now - dq[0] > AUTH_FAIL_WINDOW_S:
            dq.popleft()
        if len(dq) >= AUTH_FAIL_MAX:
            self._banned_until[ip] = now + AUTH_FAIL_BAN_S

    # ---- client frame handlers --------------------------------------------
    async def _submit_and_ack(self, s: Session, text: str, source: str,
                              priority: str = 'normal',
                              text_id: Optional[str] = None):
        if self.engine is None:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_INTERNAL'})
            return None
        snap = await self.engine.submit(text=text, priority=priority,
                                        source=source, session=s.sid)
        s.jobs.add(snap['id'])
        # instant cached ack (PROTOCOL §3) — job already allocated
        await self._send(s, {'type': 'ack', 'v': 1, 'job': snap['job'],
                             'text_id': text_id})
        return snap

    async def _on_command(self, s: Session, msg: Dict[str, Any]):
        text = (msg.get('text') or '').strip()
        if not text:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_BAD_MSG',
                                 'detail': 'command.text required'})
            return
        if self.engine is None:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_INTERNAL'})
            return
        source = msg.get('source') if msg.get('source') in ('text', 'voice', 'orb') else 'text'
        priority = msg.get('priority') or 'normal'
        # HARDENING (Wave 2 task 3): while a confirmation is pending, a VOICE
        # command that clearly says yes/no is first interpreted as that
        # confirmation's answer — a high-risk "yes" from the open mic is
        # rejected, never granted. Anything else stays a normal command.
        if source == 'voice' and self.engine.confirmer.pending_ids():
            answer = _clear_yes_no(text)
            if answer is not None:
                result, _rowid = self.engine.confirmer.resolve_oldest_pending(
                    answer, via='voice')
                if result == 'ok':
                    await self._send(s, {'type': 'ack', 'v': 1,
                                         'job': None, 'confirm_answer': True,
                                         'accepted': True})
                    self.refresh_orb_state()
                    return
                if result == 'rejected_channel':
                    self.broadcast({'type': 'subtitle', 'v': 1, 'job': None,
                                    'text': 'High-risk action — confirm from '
                                            'the orb or by typing, not voice.',
                                    'fade_ms': 6000}, roles={'ui', 'cli'})
                    await self._send(s, {'type': 'ack', 'v': 1, 'job': None,
                                         'confirm_answer': True,
                                         'accepted': False})
                    return
                # 'none' — raced to completion; fall through
        await self._submit_and_ack(s, text, source, priority,
                                   msg.get('job_id'))

    async def _on_cancel(self, s: Session, msg: Dict[str, Any]):
        if self.engine is None:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_INTERNAL'})
            return
        ref = msg.get('job') or 'all'
        scope = msg.get('scope') if msg.get('scope') in ('gui', 'full') else 'full'
        if ref == 'all':
            n = self.engine.cancel_all(scope=scope)
            await self._send(s, {'type': 'ack', 'v': 1, 'job': None,
                                 'cancelled': True, 'count': n})
            return
        job = self.engine.cancel(ref, scope=scope)
        if job is None:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_BAD_MSG',
                                 'detail': 'unknown job'})
            return
        await self._send(s, {'type': 'ack', 'v': 1, 'job': job['job'],
                             'cancelled': True, 'status': job['status']})

    async def _on_confirm_resp(self, s: Session, msg: Dict[str, Any]):
        if self.engine is None:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_INTERNAL'})
            return
        rowid = store.parse_job_ref(msg.get('job'))
        answer = msg.get('answer') or ''
        # Channel (Wave 2 task 3): explicit via wins; otherwise role-derived —
        # body = voice (STT), ui = orb click, cli = typed.
        via = msg.get('via')
        if via not in ('voice', 'click', 'text'):
            via = {'body': 'voice', 'ui': 'click', 'cli': 'text'}.get(s.role, 'text')
        result = self.engine.confirmer.resolve_ex(rowid, answer, via=via)
        if result == 'none':
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_BAD_MSG',
                                 'detail': 'no pending confirmation for job'})
            return
        if result == 'rejected_channel':
            # high-risk x voice x yes: REJECTED — pending stays, user must
            # use the orb or keyboard (timeout still aborts).
            self.broadcast({'type': 'subtitle', 'v': 1, 'job': msg.get('job'),
                            'text': 'High-risk action — confirm from the orb '
                                    'or by typing, not by voice.',
                            'fade_ms': 6000}, roles={'ui', 'cli'})
            await self._send(s, {'type': 'ack', 'v': 1, 'job': msg.get('job'),
                                 'answer': answer, 'accepted': False,
                                 'hint': 'non-voice confirmation required'})
            return
        await self._send(s, {'type': 'ack', 'v': 1, 'job': msg.get('job'),
                             'answer': answer, 'accepted': True})

    async def _on_control(self, s: Session, msg: Dict[str, Any]):
        action = msg.get('action')
        persist = bool(msg.get('persist', True))
        try:
            result = apply_control(action, persist=persist)
        except ValueError as e:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_BAD_MSG',
                                 'detail': str(e)})
            return
        await self._send(s, {'type': 'ack', 'v': 1, **result})
        self.refresh_orb_state()

    async def _on_state_req(self, s: Session, msg: Dict[str, Any]):
        # INTERFACES §e: same builder as every other emission, + server_v.
        from . import orbstate
        frame = orbstate.build(engine=self.engine,
                               extra={'server_v': SERVER_V})
        await self._send(s, frame)

    async def _on_job_list(self, s: Session, msg: Dict[str, Any]):
        await self._send(s, {'type': 'job_list', 'v': 1, 'jobs': store.list_jobs()})

    async def _on_job_get(self, s: Session, msg: Dict[str, Any]):
        job = store.get_job(msg.get('job'))
        if job is None:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_BAD_MSG',
                                 'detail': 'unknown job'})
            return
        await self._send(s, {'type': 'job_get', 'v': 1, 'job': job})

    async def _on_orb_input(self, s: Session, msg: Dict[str, Any]):
        kind = msg.get('kind')
        # Typed input channel (Wave 2 task 2 / lane task): orb text entry.
        if kind == 'submit_text':
            value = (msg.get('value') or '').strip()
            if not value:
                await self._send(s, {'type': 'error', 'v': 1,
                                     'code': 'E_BAD_MSG',
                                     'detail': 'orb_input.value required'})
                return
            await self._submit_and_ack(s, value, 'orb')
            return
        # Orb confirmation click (Wave 2 task 3): the NON-voice answer path
        # for high-risk actions (menu item / explicit confirm).
        if kind in ('menu', 'click', 'confirm') and self.engine is not None \
                and self.engine.confirmer.pending_ids():
            value = msg.get('value') or msg.get('answer') or ''
            if value:
                result, rowid = self.engine.confirmer.resolve_oldest_pending(
                    str(value), via='click')
                if result == 'ok':
                    job_snap = store.get_job(rowid) if rowid else None
                    job = job_snap['job'] if job_snap else None
                    await self._send(s, {'type': 'ack', 'v': 1, 'job': job,
                                         'answer': str(value),
                                         'accepted': True})
                    self.refresh_orb_state()
                    return
                if result == 'rejected_channel':
                    # click is always an acceptable channel — defensive only
                    await self._send(s, {'type': 'ack', 'v': 1, 'job': None,
                                         'accepted': False})
                    return
        # plain interaction — acknowledged; deeper menu wiring is orb-dev's side
        await self._send(s, {'type': 'ack', 'v': 1, 'kind': kind})

    async def _on_act_res(self, s: Session, msg: Dict[str, Any]):
        """Body -> Brain: act_req result (PROTOCOL §7).

        Was DUPLICATED (a second def shadowed the delivering one — class-body
        later-def-wins — every act_res got journaled-and-ignored and the loop
        timed out with E_ACT_TIMEOUT in the live E2E). Single merged handler:
        deliver to the waiting job FIRST, journal with a delivered flag, ack.
        """
        ref = msg.get('job')
        if not isinstance(ref, str) or not ref:
            await self._send(s, {'type': 'error', 'v': 1, 'code': 'E_BAD_MSG',
                                 'detail': 'act_res.job required'})
            return
        res = {'ok': bool(msg.get('ok')),
               'result': msg.get('result'),
               'error': msg.get('error')}
        delivered = False
        if self.engine is not None:
            delivered = self.engine.deliver_act_res(ref, res)
        rowid = store.parse_job_ref(ref)
        if rowid is not None:
            store._log_event(rowid, {'event': 'act_res',
                                     'delivered': delivered,
                                     'ok': msg.get('ok'),
                                     'result': str(msg.get('result'))[:200] if msg.get('result') is not None else None,
                                     'error': msg.get('error')})
        await self._send(s, {'type': 'ack', 'v': 1, 'job': ref})

    async def _on_audio_start(self, s: Session, msg: Dict[str, Any]):
        # mic lane (voice-dev): binary frames follow
        reason = msg.get('reason') if msg.get('reason') in ('ptt', 'wake') else 'wake'
        s.audio_reason = reason
        
        # Barge-in check: if Raphael is speaking, interrupt immediately
        from brain.voice import get_voice
        voice = get_voice()
        if voice.interrupts.any_active():
            voice.interrupts.interrupt()
            
        # Clear buffer for new utterance
        s.audio_buf = bytearray()

        # INTERFACES §e: audio_start(reason wake|ptt) -> orb `listening`
        # (takes precedence over any in-flight speaking).
        from . import orbstate
        orbstate.listening_on()
        orbstate.emit('listening', hub=self, engine=self.engine)

        await self._send(s, {'type': 'ack', 'v': 1, 'audio': 'start'})

    async def _on_audio_end(self, s: Session, msg: Dict[str, Any]):
        # INTERFACES §e: mic closed -> leave `listening` (idle if no job ran,
        # thinking once a transcript submits a job — refresh happens below).
        from . import orbstate
        orbstate.listening_off()
        if not hasattr(s, 'audio_buf') or not s.audio_buf:
            self.refresh_orb_state()
            await self._send(s, {'type': 'ack', 'v': 1, 'audio': 'end'})
            return
            
        buf = bytes(s.audio_buf)
        s.audio_buf = bytearray()
        reason = getattr(s, 'audio_reason', 'wake')
        try:
            import numpy as _np
            _x = _np.frombuffer(buf, dtype='<i2')
            _rms = float(_np.sqrt(_np.mean(_x.astype(_np.float64) ** 2))) if _x.size else 0.0
            print(f"[ws] audio_end: {len(buf)}B ({len(buf)/32000:.2f}s) "
                  f"rms={_rms:.0f} reason={reason}", flush=True)
        except Exception:  # noqa: BLE001
            print(f"[ws] audio_end: {len(buf)}B reason={reason}", flush=True)
        
        from brain.voice import get_voice, stt_final_frame, error_frame, VoiceSTTError
        voice = get_voice()
        
        try:
            # ARCHITECTURE §4: no blocking calls on the loop; HARD timeout so
            # a stuck whisper can never hang the session ("don't get stuck" —
            # TimeoutError falls into the generic except -> error frame + ack).
            res = await asyncio.wait_for(
                asyncio.to_thread(voice.transcribe_result, buf), timeout=120)
            
            # 1. Broadcast transcript to Body and UI
            self.broadcast(stt_final_frame(res.text, res.lang, res.rtf), roles={'body', 'ui'})

            # 1b. Voice-confirm interception (Wave 2 task 3): a pending
            # confirmation consumes a clear yes/no utterance HERE — voice
            # "yes" on a HIGH-risk action is rejected (pending stays, hint
            # subtitle), voice "no"/deny always works.
            if self.engine is not None and self.engine.confirmer.pending_ids():
                answer = _clear_yes_no(res.text)
                if answer is not None:
                    result, _row = self.engine.confirmer.resolve_oldest_pending(
                        answer, via='voice')
                    if result == 'ok':
                        self.refresh_orb_state()
                        await self._send(s, {'type': 'ack', 'v': 1,
                                             'audio': 'end'})
                        return
                    if result == 'rejected_channel':
                        self.broadcast({'type': 'subtitle', 'v': 1, 'job': None,
                                        'text': 'High-risk action — confirm '
                                                'from the orb or by typing, '
                                                'not voice.', 'fade_ms': 6000},
                                       roles={'ui', 'cli'})
                        # pending stays: orb/typed confirm or timeout abort

            # 2. WakeGate handling
            match = voice.wake.gate(res.text, reason=reason)
            if match.kind != 'none':
                # submit transcript with wake word stripped
                if self.engine is not None:
                    await self.engine.submit(text=match.command, priority='user_facing', source='voice', session=s.sid)
                    
        except VoiceSTTError as e:
            orbstate.mark_error()
            self.broadcast(error_frame(e.code, e.detail), roles={'body', 'ui'})
        except Exception as e:
            orbstate.mark_error()
            self.broadcast(error_frame('E_INTERNAL', str(e)), roles={'body', 'ui'})

        self.refresh_orb_state()
        await self._send(s, {'type': 'ack', 'v': 1, 'audio': 'end'})


_ORB_STATES = {
    'starting', 'reconnecting', 'offline', 'idle', 'listening', 'thinking',
    'acting', 'speaking', 'confirm', 'error', 'private_overlay',
}


_hub: Optional[WsHub] = None


def get_hub() -> WsHub:
    global _hub
    if _hub is None:
        _hub = WsHub()
    return _hub
