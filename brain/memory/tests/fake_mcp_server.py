"""Fake MCP stdio server for tools-memory tests (JSON-RPC 2.0, line-based).

argv[1] = mode: 'normal' (default) | 'hang' (never answers tools/list).
Implements: initialize, tools/list (echo + lax-schema + weird-schema tools),
tools/call (echo/lax succeed; anything else -> isError), notifications are
acknowledged by ignoring, unknown methods -> -32601.
"""
import json
import sys
import time

MODE = sys.argv[1] if len(sys.argv) > 1 else 'normal'

TOOLS = [
    {'name': 'echo',
     'description': 'echo text back',
     'inputSchema': {'type': 'object',
                     'properties': {'text': {'type': 'string',
                                             'description': 'text to echo'}},
                     'required': ['text'],
                     'additionalProperties': False}},
    # lax on purpose: no required, no additionalProperties, undescribed prop
    {'name': 'lax',
     'description': 'lax schema tool',
     'inputSchema': {'type': 'object',
                     'properties': {'x': {'type': 'string'}}}},
    # cannot be tightened: inputSchema is not even an object
    {'name': 'weird',
     'description': 'cannot tighten',
     'inputSchema': 'nope'},
]


def _send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
    sys.stdout.flush()


for _line in sys.stdin:
    _line = _line.strip()
    if not _line:
        continue
    try:
        msg = json.loads(_line)
    except ValueError:
        continue
    if not isinstance(msg, dict):
        continue
    mid = msg.get('id')
    method = msg.get('method')
    if mid is None:                       # notification (initialized, etc.)
        continue
    if MODE == 'hang' and method == 'tools/list':
        time.sleep(120)                   # killed by the test's shutdown
        continue
    if method == 'initialize':
        _send({'jsonrpc': '2.0', 'id': mid, 'result': {
            'protocolVersion': '2024-11-05',
            'capabilities': {'tools': {}},
            'serverInfo': {'name': 'fake', 'version': '1.0'}}})
    elif method == 'tools/list':
        _send({'jsonrpc': '2.0', 'id': mid, 'result': {'tools': TOOLS}})
    elif method == 'tools/call':
        params = msg.get('params') or {}
        name = params.get('name')
        args = params.get('arguments') or {}
        if name == 'echo':
            result = {'content': [{'type': 'text',
                                   'text': f"echo: {args.get('text', '')}"}]}
        elif name == 'lax':
            result = {'content': [{'type': 'text',
                                   'text': f"lax {args.get('x', '')}"}]}
        else:
            result = {'content': [{'type': 'text',
                                   'text': f'unknown tool {name}'}],
                      'isError': True}
        _send({'jsonrpc': '2.0', 'id': mid, 'result': result})
    else:
        _send({'jsonrpc': '2.0', 'id': mid,
               'error': {'code': -32601, 'message': 'unknown method'}})
