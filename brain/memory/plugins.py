"""Plugins — user-authored drop-in CODE skills: manifest loader.

Layout: `plugins/<name>/manifest.yaml` (or .yml / .json):

    name: my_plugin            # [a-z0-9_-], strict (no path tricks)
    version: "1.0"
    description: what it adds
    entry: __init__.py         # python file, imported ONLY when enabled
    enabled: false             # FAIL-CLOSED: missing = false, always
    tools:
      - name: my_tool          # [a-z0-9_], must NOT collide with core tools
        description: shown to the model (required by the registry)
        risky: true            # default TRUE — unknown external behavior
        schema: {type: object, properties: {...}, required: [...],
                 additionalProperties: false}

Security model (AGENT_RULES §8 spirit):
- scanning/validating NEVER imports anything — import happens only in
  `load_enabled()` for `enabled: true` manifests (`plugins.auto_enable`
  default false: without it the flag alone counts);
- manifests are USER code authority — the MODEL cannot create, enable or
  modify them (learned, model-written skills live in `skills/` instead);
- a plugin tool may NEVER shadow an already-registered tool (refuse + record);
- schemas pass the central registry's strict `validate_schema` (INTERFACES §b)
  or the tool is skipped, loud in the error report;
- one broken plugin never blocks the others (per-plugin fail-silent).
"""
import importlib.util
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

NAME_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
TOOL_RE = re.compile(r'^[a-z0-9][a-z0-9_]{0,63}$')
_MANIFESTS = ('manifest.yaml', 'manifest.yml', 'manifest.json')

_loaded_modules: Dict[str, Any] = {}   # keep refs: imported plugins stay alive


class PluginError(ValueError):
    """Malformed manifest — recorded per plugin, never fatal."""


def _cfg(dotted: str, default: Any) -> Any:
    try:
        from .. import config as appcfg
        return appcfg.cfg_get(appcfg.get_config(), dotted, default)
    except Exception:  # noqa: BLE001
        return default


def plugins_dir() -> Path:
    raw = str(_cfg('plugins.dir', 'plugins') or 'plugins')
    p = Path(raw).expanduser()
    if not p.is_absolute():
        from .. import config as appcfg
        p = appcfg.REPO_ROOT / p
    return p


def _read_manifest(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding='utf-8')
    if path.suffix == '.json':
        data = json.loads(text)
    else:
        import yaml
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise PluginError('manifest must be a mapping')
    return data


def validate(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Structural validation -> normalized record. Raises PluginError."""
    name = str(manifest.get('name') or '')
    if not NAME_RE.match(name):
        raise PluginError(f'invalid plugin name {name!r} (need {NAME_RE.pattern})')
    enabled = bool(manifest.get('enabled', False))   # missing = fail-closed
    if not isinstance(manifest.get('enabled', False), bool):
        raise PluginError('enabled must be a boolean')
    tools = manifest.get('tools') or []
    if not isinstance(tools, list):
        raise PluginError('tools must be a list')
    norm_tools: List[Dict[str, Any]] = []
    for t in tools:
        if not isinstance(t, dict):
            raise PluginError('each tool must be a mapping')
        tname = str(t.get('name') or '')
        if not TOOL_RE.match(tname):
            raise PluginError(f'invalid tool name {tname!r} (need {TOOL_RE.pattern})')
        tdesc = str(t.get('description') or '').strip()
        if not tdesc:
            raise PluginError(f'tool {tname!r} needs a description')
        schema = t.get('schema')
        if schema is not None:
            if not isinstance(schema, dict) or schema.get('type') != 'object':
                raise PluginError(f'tool {tname!r} schema must be an object schema')
        norm_tools.append({
            'name': tname,
            'description': tdesc,
            'risky': bool(t.get('risky', True)),     # default TRUE
            'schema': schema,
        })
    entry = manifest.get('entry')
    if entry is not None and not isinstance(entry, str):
        raise PluginError('entry must be a path string')
    return {
        'name': name,
        'version': str(manifest.get('version') or '0'),
        'description': str(manifest.get('description') or ''),
        'enabled': enabled,
        'entry': entry,
        'tools': norm_tools,
    }


def _manifest_paths(directory: Optional[Path] = None) -> List[Path]:
    d = Path(directory) if directory else plugins_dir()
    if not d.is_dir():
        return []
    out = []
    for child in sorted(d.iterdir()):
        if not child.is_dir():
            continue
        for mn in _MANIFESTS:
            p = child / mn
            if p.is_file():
                out.append(p)
                break
    return out


def _upsert_index(rec: Dict[str, Any], path: str, error: Optional[str]) -> None:
    from . import get_conn
    conn = get_conn()
    try:
        now = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
        conn.execute(
            'INSERT INTO plugins_index (name, path, description, version, '
            'enabled, tools, last_error, updated_at) VALUES (?,?,?,?,?,?,?,?) '
            'ON CONFLICT(name) DO UPDATE SET path=excluded.path, '
            'description=excluded.description, version=excluded.version, '
            'enabled=excluded.enabled, tools=excluded.tools, '
            'last_error=excluded.last_error, updated_at=excluded.updated_at',
            (rec['name'], path, rec['description'], rec['version'],
             1 if rec['enabled'] else 0,
             json.dumps([t['name'] for t in rec['tools']]), error, now))
        conn.commit()
    finally:
        conn.close()


def scan(*, directory: Optional[Path] = None) -> Dict[str, Any]:
    """Find + validate manifests, mirror to plugins_index. NEVER imports.
    Fail-silent per manifest: bad ones land in `errors`."""
    out: Dict[str, Any] = {'plugins': [], 'errors': {}}
    try:
        for p in _manifest_paths(directory):
            try:
                rec = validate(_read_manifest(p))
                _upsert_index(rec, str(p), None)
                out['plugins'].append(rec)
            except Exception as e:  # noqa: BLE001 — one bad plugin != no plugins
                out['errors'][str(p)] = f'{type(e).__name__}: {e}'
                _record_error(p.parent.name, out['errors'][str(p)], p)
    except Exception as e:  # noqa: BLE001
        out['errors']['<scan>'] = f'{type(e).__name__}: {e}'
    return out


def load_enabled(*, directory: Optional[Path] = None) -> Dict[str, Any]:
    """Import enabled manifests and register their tools (startup seam;
    brain-core wiring requested in docs/requests/
    tools-memory__to__brain-core__loop-memory-skills-injection).

    Returns {'registered': [...], 'errors': {plugin_or_tool: msg}}.
    Per-plugin fail-silent; refuses tool-name collisions (never shadow)."""
    out: Dict[str, Any] = {'registered': [], 'errors': {}}
    auto = bool(_cfg('plugins.auto_enable', False))
    try:
        from .. import tools as tool_reg
    except Exception as e:  # noqa: BLE001 — registry unavailable: nothing to do
        out['errors']['<registry>'] = f'{type(e).__name__}: {e}'
        return out

    for p in _manifest_paths(directory):
        pname = p.parent.name
        try:
            rec = validate(_read_manifest(p))
        except Exception as e:  # noqa: BLE001
            out['errors'][pname] = f'{type(e).__name__}: {e}'
            _record_error(pname, out['errors'][pname], p)
            continue
        if not (rec['enabled'] or auto):
            continue                       # fail-closed: not enabled -> no import
        if not rec['entry']:
            out['errors'][pname] = 'enabled but no `entry` to import'
            _record_error(pname, out['errors'][pname], p)
            continue
        entry_path = (p.parent / rec['entry']).resolve()
        if not entry_path.is_file():
            out['errors'][pname] = f'entry not found: {rec["entry"]}'
            _record_error(pname, out['errors'][pname], p)
            continue
        try:
            mod_name = f'raphael_plugin_{rec["name"]}'
            spec = importlib.util.spec_from_file_location(mod_name, entry_path)
            if spec is None or spec.loader is None:
                raise PluginError('cannot build import spec')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)      # USER code runs here, by design
            _loaded_modules[rec['name']] = module
        except Exception as e:  # noqa: BLE001
            out['errors'][pname] = f'import failed: {type(e).__name__}: {e}'
            _record_error(pname, out['errors'][pname], p)
            continue

        plugin_ok = True
        for t in rec['tools']:
            tkey = f'{pname}.{t["name"]}'
            if tool_reg.get(t['name']) is not None:
                out['errors'][tkey] = 'refuses to shadow an existing tool'
                plugin_ok = False
                continue
            fn = getattr(module, t['name'], None)
            if not callable(fn):
                out['errors'][tkey] = 'entry module has no such callable'
                plugin_ok = False
                continue
            schema = t['schema']
            if schema is not None:
                try:
                    tool_reg.validate_schema(t['name'], schema)
                except Exception as e:  # noqa: BLE001
                    out['errors'][tkey] = f'schema rejected: {e}'
                    plugin_ok = False
                    continue
            tool_reg.register(
                t['name'], fn, risky=t['risky'], needs_lock=False,
                description=t['description'], category='local',
                schema=schema)
            out['registered'].append(t['name'])
        _record_error(pname, None if plugin_ok
                      else '; '.join(f'{k}: {v}' for k, v in out['errors'].items()
                                     if k.startswith(pname + '.')), p)
    return out


def _record_error(pname: str, error: Optional[str], path: Path) -> None:
    try:
        rec = validate(_read_manifest(path))
    except Exception:  # noqa: BLE001 — even broken manifests get visibility
        rec = {'name': pname, 'version': '0', 'description': '',
               'enabled': False, 'entry': None, 'tools': []}
    _upsert_index(rec, str(path), error)
