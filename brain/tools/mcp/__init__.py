"""MCP client adapter — MCP servers register as Raphael tools (plan §3.6).

Trust model:
- servers exist ONLY in `config.d/tools-memory.yaml → mcp.servers`
  (user-authored: spawning a stdio command = running code = the USER's
  authority, granted by writing the config). The MODEL can never add,
  start or reconfigure a server — it can only `mcp_list` and call what
  the allow-list permits;
- **allow-list fail-closed**: `allow: []` (default) = server may be listed
  but ZERO of its tools are callable; `"*"` is the explicit opt-in;
- **confirm categories**: wrapped tools default `risky=True` (unknown
  external behavior → confirm gate fires); `confirm: {tool: false}` is a
  USER-authored relaxation, never model-settable;
- **untrusted output**: every result is a plain string the loop wraps with
  `as_untrusted()` before any model sees it (MCP results are a known
  prompt-injection vector — AGENT_RULES §9);
- server schemas are TIGHTENED to the strict INTERFACES §b contract
  (`additionalProperties: False`, typed+described props, `required`
  normalized) — never loosened; tools that can't be tightened are skipped
  LOUDLY in the error report, not silently registered.

Boot: `refresh()` runs once at import (discovery) — with the default
`servers: []` that is a no-op; with configured servers it connects with a
short timeout and registers what it can. `mcp_refresh` re-runs it.
"""
from __future__ import annotations

import re
import threading
from typing import Any, Dict, List, Optional, Tuple

import brain.tools as _tool_reg

from .client import McpError, StdioClient  # noqa: F401 — re-exported seam

_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,31}$')
_TOOL_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')

_lock = threading.Lock()
_clients: Dict[str, StdioClient] = {}
_inventory: Dict[str, Dict[str, Any]] = {}   # server -> {tools, callable, error}
_booted = False

SPECS = {
    'mcp_list': {
        'type': 'object', 'properties': {}, 'required': [],
        'additionalProperties': False,
    },
    'mcp_refresh': {
        'type': 'object', 'properties': {}, 'required': [],
        'additionalProperties': False,
    },
}


def _cfg(dotted: str, default):
    try:
        from brain import config as appcfg
        return appcfg.cfg_get(appcfg.get_config(), dotted, default)
    except Exception:  # noqa: BLE001
        return default


# ---- config -----------------------------------------------------------------
def _servers() -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    raw = _cfg('mcp.servers', []) or []
    valid: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}
    if not isinstance(raw, list):
        return [], {'mcp.servers': 'must be a list'}
    for i, entry in enumerate(raw):
        key = f'mcp.servers[{i}]'
        if not isinstance(entry, dict):
            errors[key] = 'must be a mapping'
            continue
        name = str(entry.get('name') or '')
        if not _NAME_RE.match(name):
            errors[key] = f'invalid name {name!r} (need {_NAME_RE.pattern})'
            continue
        transport = str(entry.get('transport') or 'stdio')
        if transport != 'stdio':
            errors[key] = f'transport {transport!r} unsupported (stdio only)'
            continue
        cmd = entry.get('command')
        if not isinstance(cmd, (list, tuple)) or not cmd or \
                not all(isinstance(c, (str, int, float)) for c in cmd):
            errors[key] = 'command must be a non-empty argv list'
            continue
        allow = entry.get('allow') or []
        if not isinstance(allow, list) or \
                not all(isinstance(a, str) for a in allow):
            errors[key] = 'allow must be a list of tool names ("*" = all)'
            continue
        confirm = entry.get('confirm') or {}
        if not isinstance(confirm, dict):
            errors[key] = 'confirm must be a mapping of tool -> bool'
            continue
        env = entry.get('env') or {}
        if not isinstance(env, dict):
            errors[key] = 'env must be a mapping'
            continue
        try:
            timeout = float(entry.get(
                'timeout_s', _cfg('mcp.timeout_s', 10) or 10))
        except (TypeError, ValueError):
            errors[key] = 'timeout_s must be a number'
            continue
        valid.append({
            'name': name,
            'command': [str(c) for c in cmd],
            'allow': list(allow),
            'confirm': {str(k): bool(v) for k, v in confirm.items()},
            'timeout': timeout,
            'env': {str(k): str(v) for k, v in env.items()},
        })
    return valid, errors


def _allowed(cfg_srv: Dict[str, Any], tool: str) -> bool:
    allow = cfg_srv.get('allow') or []
    return tool in allow or '*' in allow


# ---- schema adaptation ------------------------------------------------------
def _strictify(schema: Any) -> Dict[str, Any]:
    """Tighten a server's inputSchema to INTERFACES §b. Raises ValueError on
    schemas that cannot be tightened without guessing (never loosens)."""
    if not isinstance(schema, dict):
        raise ValueError('inputSchema must be an object schema')
    out = dict(schema)
    out['type'] = 'object'
    props_in = out.get('properties')
    if props_in is None:
        props_in = {}
    if not isinstance(props_in, dict):
        raise ValueError('properties must be a mapping')
    props: Dict[str, Any] = {}
    for k, v in props_in.items():
        if not isinstance(v, dict):
            raise ValueError(f'property {k!r} must be a mapping')
        pv = dict(v)
        if 'type' not in pv:
            raise ValueError(f'property {k!r} has no "type" — cannot tighten')
        if not str(pv.get('description') or '').strip():
            pv['description'] = str(k)
        props[str(k)] = pv
    out['properties'] = props
    required = out.get('required')
    if required is None:
        required = []
    if not isinstance(required, list):
        raise ValueError('required must be a list')
    out['required'] = [str(r) for r in required if str(r) in props]
    out['additionalProperties'] = False
    return out


def _normalize_tools(payload: Any) -> Tuple[List[Dict[str, Any]], List[str]]:
    out: List[Dict[str, Any]] = []
    errs: List[str] = []
    tools = payload.get('tools') if isinstance(payload, dict) else None
    for t in tools or []:
        if not isinstance(t, dict):
            errs.append('tool entry not a mapping')
            continue
        name = str(t.get('name') or '')
        if not _TOOL_NAME_RE.match(name):
            errs.append(f'skipped invalid tool name {name!r}')
            continue
        desc = ' '.join(str(t.get('description') or '').split()) or \
            f'MCP tool {name}'
        try:
            schema = _strictify(t.get('inputSchema'))
            _tool_reg.validate_schema(name, schema)     # loud contract check
        except Exception as e:  # noqa: BLE001 — skip + report, never crash
            errs.append(f'{name}: {e}')
            continue
        out.append({'name': name, 'description': desc, 'schema': schema})
    return out, errs


# ---- clients / refresh ------------------------------------------------------
def _ensure_client(cfg_srv: Dict[str, Any]) -> StdioClient:
    name = cfg_srv['name']
    with _lock:
        cli = _clients.get(name)
        if cli is not None and cli.alive():
            return cli
        if cli is not None:
            cli.close()
            _clients.pop(name, None)
    # spawn OUTSIDE the lock (spawning can take a moment)
    cli = StdioClient(cfg_srv['command'], timeout=cfg_srv['timeout'],
                      env=cfg_srv['env'] or None)
    try:
        cli.handshake()
    except Exception:
        cli.close()
        raise
    with _lock:
        prev = _clients.get(name)
        if prev is not None and prev is not cli:
            prev.close()                          # lost a race: keep one child
        _clients[name] = cli
    return cli


def _register_dynamic(cfg_srv: Dict[str, Any], tools: List[Dict[str, Any]]):
    registered: List[str] = []
    errors: Dict[str, str] = {}
    for t in tools:
        if not _allowed(cfg_srv, t['name']):
            continue                              # fail-closed allow-list
        tname = f"mcp_{cfg_srv['name']}_{t['name']}"
        if _tool_reg.get(tname) is not None:
            errors[tname] = 'refuses to shadow an existing tool'
            continue
        # risky: USER-authored per-tool override wins when present; default
        # TRUE (unknown external behavior). confirm:{tool:false} relaxes —
        # that key only exists in the user's own config, never model-settable.
        risky = bool(cfg_srv['confirm'].get(t['name'], True))
        _tool_reg.register(
            tname, _make_call(cfg_srv['name'], t['name']),
            risky=risky, needs_lock=False, category='local',
            description=f"{t['description']} [MCP {cfg_srv['name']}]",
            schema=t['schema'])
        registered.append(tname)
    return registered, errors


def refresh(force: bool = False) -> Dict[str, Any]:
    """(Re)connect every configured server, list its tools, register the
    allow-listed ones. Per-server fail-silent: one broken server never
    blocks the others. Returns {'registered': [...], 'errors': {...}}."""
    global _booted
    out: Dict[str, Any] = {'registered': [], 'errors': {}}
    with _lock:
        if _booted and not force:
            return {'registered': [], 'errors': {}}
        _booted = True
    cfgs, cfg_errors = _servers()
    out['errors'].update(cfg_errors)
    for cfg_srv in cfgs:
        sname = cfg_srv['name']
        try:
            cli = _ensure_client(cfg_srv)
            payload = cli.request('tools/list', timeout=cfg_srv['timeout'])
            tools, tool_errs = _normalize_tools(payload)
            allowed = [t for t in tools if _allowed(cfg_srv, t['name'])]
            reg, reg_errs = _register_dynamic(cfg_srv, allowed)
            out['registered'].extend(reg)
            out['errors'].update(reg_errs)
            if tool_errs:
                out['errors'][f'{sname}.tools'] = '; '.join(tool_errs[:5])
            _inventory[sname] = {
                'callable': [t['name'] for t in allowed],
                'hidden': len(tools) - len(allowed),
                'error': None,
            }
        except Exception as e:  # noqa: BLE001 — broken server != broken brain
            out['errors'][sname] = f'{type(e).__name__}: {e}'
            _inventory[sname] = {'callable': [], 'hidden': 0,
                                 'error': f'{type(e).__name__}: {e}'}
            # NEVER keep a wedged/handicapped child (timeout, EOF, dead
            # handshake): evict + close so no orphan survives a failed refresh
            with _lock:
                stale = _clients.pop(sname, None)
            if stale is not None:
                try:
                    stale.close()
                except Exception:  # noqa: BLE001
                    pass
    return out


def _make_call(server: str, tool: str):
    def _call(**kwargs: Any) -> str:
        return _call_tool(server, tool, kwargs)
    return _call


def _call_tool(server: str, tool: str, arguments: Dict[str, Any]) -> str:
    cfgs, _ = _servers()
    cfg_srv = next((c for c in cfgs if c['name'] == server), None)
    if cfg_srv is None:
        raise McpError(f'server {server!r} no longer configured')
    if not _allowed(cfg_srv, tool):
        raise McpError(f'tool {tool!r} is not in the allow-list for {server}')
    max_chars = int(_cfg('mcp.max_result_chars', 65536) or 65536)
    attempts = 0
    while True:
        attempts += 1
        try:
            cli = _ensure_client(cfg_srv)
            res = cli.request('tools/call',
                              {'name': tool, 'arguments': arguments},
                              timeout=cfg_srv['timeout'])
            break
        except McpError as e:
            if attempts >= 2 or 'timeout' in str(e) or 'not supported' in str(e):
                raise                                # reconnect-exactly-once
            # dead child / handshake hiccup: drop client, retry once
            with _lock:
                old = _clients.pop(server, None)
            if old is not None:
                old.close()
    parts: List[str] = []
    for item in (res.get('content') or []) if isinstance(res, dict) else []:
        if isinstance(item, dict) and item.get('type') == 'text':
            parts.append(str(item.get('text') or ''))
    text = '\n'.join(parts).strip()
    if res.get('isError') if isinstance(res, dict) else False:
        raise RuntimeError(f'MCP {server}.{tool} reported an error: '
                           f'{text[:500] or "(no text)"}')
    if not text:
        text = '(no text content)'
    if len(text) > max_chars:
        text = text[:max_chars] + '\n… [truncated]'
    return text                                     # untrusted: loop wraps


# ---- static tools -----------------------------------------------------------
def mcp_list() -> str:
    """Inventory of configured MCP servers + which tools are CALLABLE."""
    if not _booted:
        refresh()
    cfgs, cfg_errors = _servers()
    lines: List[str] = []
    for cfg_srv in cfgs:
        inv = _inventory.get(cfg_srv['name']) or {}
        if inv.get('error'):
            status = f'ERROR: {inv["error"]}'
        else:
            callable_names = inv.get('callable') or []
            status = 'ok' if callable_names else \
                'ok (0 callable — allow-list is fail-closed)'
        lines.append(f"- {cfg_srv['name']}: {status}")
        if inv.get('callable'):
            lines.append('  callable: ' + ', '.join(
                f"mcp_{cfg_srv['name']}_{t}" for t in inv['callable']))
        if inv.get('hidden'):
            lines.append(f"  {inv['hidden']} tool(s) hidden by the allow-list")
    for key, err in cfg_errors.items():
        lines.append(f'- CONFIG {key}: {err}')
    if not lines:
        return ('no MCP servers configured (mcp.servers is empty — add '
                'servers in config.d/tools-memory.yaml; the model cannot '
                'add servers itself)')
    return '\n'.join(lines)


def mcp_refresh() -> str:
    """Reconnect all configured servers and re-register their allow-listed
    tools (after a crash or config restart)."""
    global _booted
    with _lock:
        _booted = False
    out = refresh(force=True)
    n = len(out['registered'])
    if out['errors']:
        return (f'registered {n} tool(s); errors: ' +
                '; '.join(f'{k}: {v}' for k, v in out['errors'].items())[:800])
    return f'registered {n} tool(s)'


def shutdown_clients() -> None:
    """Close every spawned server child (Rule 14: zero orphans)."""
    with _lock:
        clients = list(_clients.values())
        _clients.clear()
    for cli in clients:
        try:
            cli.close()
        except Exception:  # noqa: BLE001
            pass


def register(_reg=None) -> None:
    reg = _reg if _reg is not None and hasattr(_reg, 'register') else _tool_reg
    reg.register('mcp_list', mcp_list, risky=False, category='local',
                 description='list configured MCP servers and their '
                             'callable (allow-listed) tools',
                 schema=SPECS['mcp_list'])
    reg.register('mcp_refresh', mcp_refresh, risky=False, category='local',
                 description='reconnect MCP servers and re-register '
                             'allow-listed tools',
                 schema=SPECS['mcp_refresh'])


register()


def _boot() -> None:
    """Discovery-time connect: no-op with the default empty config."""
    try:
        cfgs, _ = _servers()
        if cfgs:
            refresh()
    except Exception:  # noqa: BLE001 — boot must never fail an import
        pass


_boot()
