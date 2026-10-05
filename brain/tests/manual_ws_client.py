#!/usr/bin/env python3
"""Manual WS round-trip client — brain phase-2 live verification.

Not a pytest file (no test_ prefix). Connects to a LIVE uvicorn brain and
prints the canonical frames: auth_ok → state_req/orb_state → command →
ack/job_event/subtitle → needs_confirm → confirm_resp(no) → cancelled.

Usage:
  RAPHAEL_TOKEN_PATH=/tmp/raphael-demo-token \\
      brain/.venv/bin/python brain/tests/manual_ws_client.py [ws_url]
"""
import asyncio
import json
import os
import sys

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else 'ws://127.0.0.1:8765/ws'
TOKEN_PATH = os.environ.get('RAPHAEL_TOKEN_PATH') or os.path.expanduser('~/.raphael/token')
TOKEN = open(TOKEN_PATH).read().strip()


def show(tag, msg):
    print(f'  [{tag}] {json.dumps(msg, ensure_ascii=False)[:220]}')


async def recv_until(ws, pred, skip=('ping',), limit=60, timeout=10):
    for _ in range(limit):
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        show('recv', msg)
        if msg.get('type') in skip:
            continue
        if pred(msg):
            return msg
    raise AssertionError('predicate not met')


async def main():
    print(f'CONNECT {URL}  (token from {TOKEN_PATH})')
    async with websockets.connect(URL) as ws:
        # 1. handshake (PROTOCOL §2)
        await ws.send(json.dumps({'type': 'auth', 'v': 1, 'token': TOKEN,
                                  'role': 'cli', 'client': 'manual-demo',
                                  'client_v': '0.2'}))
        msg = await recv_until(ws, lambda m: m.get('type') in ('auth_ok', 'auth_fail'))
        assert msg['type'] == 'auth_ok', msg
        print(f"  AUTH OK session={msg['session']} server_v={msg['server_v']}")

        # 2. state snapshot round trip
        await ws.send(json.dumps({'type': 'state_req', 'v': 1}))
        msg = await recv_until(ws, lambda m: m.get('type') == 'orb_state')
        print(f"  STATE mode={msg['mode']} jobs_active={msg['jobs_active']}")

        # 3. deterministic fast-path command → job lifecycle events
        print('COMMAND: "echo hello raphael"')
        await ws.send(json.dumps({'type': 'command', 'v': 1,
                                  'text': 'echo hello raphael', 'source': 'text'}))
        msg = await recv_until(ws, lambda m: m.get('type') == 'ack')
        job = msg['job']
        print(f'  ACK job={job}')
        msg = await recv_until(ws, lambda m: m.get('type') == 'job_event'
                               and m.get('status') == 'done' and m.get('job') == job)
        print(f"  DONE text={msg['text']!r} seq={msg['seq']}")

        # 4. risky command → needs_confirm → deny → cancelled (PROTOCOL §9)
        print('COMMAND: "delete my downloads folder"')
        await ws.send(json.dumps({'type': 'command', 'v': 1,
                                  'text': 'delete my downloads folder',
                                  'source': 'text'}))
        msg = await recv_until(ws, lambda m: m.get('type') == 'ack')
        job2 = msg['job']
        msg = await recv_until(ws, lambda m: m.get('type') == 'needs_confirm'
                               and m.get('job') == job2)
        print(f"  CONFIRM question={msg['question']!r}")
        await ws.send(json.dumps({'type': 'confirm_resp', 'v': 1,
                                  'job': job2, 'answer': 'no'}))
        msg = await recv_until(ws, lambda m: m.get('type') == 'job_event'
                               and m.get('status') == 'cancelled'
                               and m.get('job') == job2)
        print(f"  CANCELLED text={msg['text']!r} error_code={msg['error_code']}")

        # 5. final status
        await ws.send(json.dumps({'type': 'state_req', 'v': 1}))
        msg = await recv_until(ws, lambda m: m.get('type') == 'orb_state')
        print(f"  FINAL STATE mode={msg['mode']} jobs_active={msg['jobs_active']}")
    print('ROUND TRIP COMPLETE')


if __name__ == '__main__':
    asyncio.run(main())
