"""Central configuration loader + instance isolation (docs/INTERFACES.md §c/§d).

Owned by the brain-core lane (OWNERSHIP.md). Nothing here talks to providers
or the network — it only resolves the effective config tree and derives
instance-scoped values.

Load order (later wins), INTERFACES §c:
  1. `config.yaml` (base, integrator-owned)
  2. `config.d/*.yaml` fragments, sorted by filename, each deep-merged over the
     accumulated tree (mappings merge recursively; lists and scalars REPLACE —
     no null-deletion magic)
  3. the active profile overlay `profiles.<profile>` from the merged tree
  4. explicit env overrides for instance values (RAPHAEL_INSTANCE, RAPHAEL_PORT,
     RAPHAEL_BIND, RAPHAEL_LOG_LEVEL)

Profile source: `RAPHAEL_PROFILE` env (wins) -> top-level `profile:` key ->
default `cloud_temp`. Secrets never appear in any yaml — `.env` only.

Instance isolation, INTERFACES §d: `RAPHAEL_INSTANCE` (default `main`) derives
the port, pidfile, data-dir, lock/mutex names and CDP port. Unset = `main` =
today's exact behavior. Code must read these helpers, never hardcode a
port/lock/path (AGENT_RULES §5).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / 'config.yaml'
CONFIG_D = REPO_ROOT / 'config.d'

DEFAULT_PROFILE = 'cloud_temp'

# (instance, ws/rest port, index) — INTERFACES §d table, verbatim.
_INSTANCES = [
    ('main', 8765, 0),
    ('router', 8901, 1),
    ('brain-core', 8902, 2),
    ('pc-control', 8903, 3),
    ('voice', 8904, 4),
    ('computer-use', 8905, 5),
    ('orb', 8906, 6),
    ('infra', 8907, 7),
    ('qa-security', 8908, 8),
    ('tools-memory', 8909, 9),
    ('evolution-persona', 8910, 10),
]
_PORT_BY_INSTANCE = {name: port for name, port, _ in _INSTANCES}
_INDEX_BY_INSTANCE = {name: idx for name, _, idx in _INSTANCES}
MAIN_CDP_PORT = 9333          # §d: main keeps 9333 (zero change)


# ---- merge helpers ---------------------------------------------------------
def deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge `over` onto `base`. Mappings merge; lists and scalars
    replace. Returns a NEW dict (neither input is mutated)."""
    out: Dict[str, Any] = dict(base)
    for key, val in (over or {}).items():
        if (key in out and isinstance(out[key], dict)
                and isinstance(val, dict)):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml
    except ImportError:  # pragma: no cover — PyYAML is a hard dep of the repo
        return {}
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    return data if isinstance(data, dict) else {}


def load_config(path: Optional[Path] = None, force: bool = False) -> Dict[str, Any]:
    """Resolve the full config tree (INTERFACES §c). Cached via get_config()."""
    global _cache, _cache_key
    base_path = Path(path) if path else CONFIG_PATH
    # env values affect the result → they belong to the cache key, otherwise a
    # profile/instance change would silently serve a stale tree.
    key = (str(base_path), force,
           os.environ.get('RAPHAEL_PROFILE'), os.environ.get('RAPHAEL_INSTANCE'),
           os.environ.get('RAPHAEL_PORT'), os.environ.get('RAPHAEL_BIND'),
           os.environ.get('RAPHAEL_LOG_LEVEL'))
    if not force and _cache is not None and _cache_key == key:
        return _cache
    cfg = _read_yaml(base_path)
    # 2. config.d fragments, filename-sorted (deterministic across machines)
    d_dir = base_path.parent / 'config.d'
    if d_dir.is_dir():
        for frag in sorted(d_dir.glob('*.yaml')):
            cfg = deep_merge(cfg, _read_yaml(frag))
    # 3. profile overlay
    prof = os.environ.get('RAPHAEL_PROFILE') or cfg.get('profile') or DEFAULT_PROFILE
    overlay = (cfg.get('profiles') or {}).get(prof) or {}
    cfg = deep_merge(cfg, overlay)
    cfg['profile'] = prof
    # 4. explicit env overrides (INTERFACES §c item 4)
    inst = instance()
    cfg['instance'] = inst
    if os.environ.get('RAPHAEL_PORT'):
        cfg.setdefault('server', {})['port'] = int(os.environ['RAPHAEL_PORT'])
    if os.environ.get('RAPHAEL_BIND'):
        cfg.setdefault('server', {})['host'] = os.environ['RAPHAEL_BIND']
    if os.environ.get('RAPHAEL_LOG_LEVEL'):
        cfg.setdefault('server', {})['log_level'] = os.environ['RAPHAEL_LOG_LEVEL']
    _cache, _cache_key = cfg, key
    return cfg


_cache: Optional[Dict[str, Any]] = None
_cache_key: Optional[Any] = None
_lock = threading.Lock()


def get_config() -> Dict[str, Any]:
    """Cached effective config (thread-safe)."""
    with _lock:
        return load_config()


def reset_config_for_tests() -> None:
    """Drop the cache so tests see env changes (name is a convention signal:
    production code never calls this)."""
    global _cache, _cache_key
    with _lock:
        _cache, _cache_key = None, None


def cfg_get(cfg: Dict[str, Any], dotted: str, default: Any = None) -> Any:
    """`cfg_get(cfg, 'jobs.confirm_timeout_s', 30)` — dotted lookup, no KeyError."""
    node: Any = cfg
    for part in dotted.split('.'):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


# ---- instance derivation (INTERFACES §d) -----------------------------------
def instance() -> str:
    """`RAPHAEL_INSTANCE` (default `main`). Never hardcoded at call sites."""
    return (os.environ.get('RAPHAEL_INSTANCE') or 'main').strip() or 'main'


def _instance_index(name: str) -> int:
    if name not in _INDEX_BY_INSTANCE:
        raise RuntimeError(
            f"RAPHAEL_INSTANCE={name!r} is not in the INTERFACES §d table — "
            f"ask the integrator to add it (ports/locks derive from that table, "
            f"never from a guess). Set RAPHAEL_PORT explicitly only if you know "
            f"what you are doing.")
    return _INDEX_BY_INSTANCE[name]


def port() -> int:
    """WS/REST port. RAPHAEL_PORT wins (run.py honors it), then the §d table."""
    env = os.environ.get('RAPHAEL_PORT')
    if env:
        return int(env)
    name = instance()
    if name in _PORT_BY_INSTANCE:
        return _PORT_BY_INSTANCE[name]
    _instance_index(name)               # raises loudly for unknown instances
    raise AssertionError('unreachable')


def cdp_port() -> int:
    name = instance()
    if name == 'main':
        return MAIN_CDP_PORT
    return 9400 + _instance_index(name)


def data_dir() -> Path:
    """`~/.raphael/` for main; `~/.raphael/<instance>/` for every lane."""
    name = instance()
    home = Path(os.environ.get('RAPHAEL_HOME') or Path.home())
    root = home / '.raphael'
    return root if name == 'main' else root / name


def pidfile() -> Path:
    """Authoritative brain pidfile — INSIDE the instance data-dir (out of /tmp:
    world-writable /tmp is shared across instances and symlink-unsafe).
    main also keeps the legacy /tmp/raphael-brain.pid (see legacy_pidfile)."""
    return data_dir() / 'brain.pid'


def legacy_pidfile() -> Optional[Path]:
    """Legacy supervisor path (supervisor/main.py reads /tmp/raphael-brain.pid).
    Kept ONLY for instance `main` so the real stack is byte-compatible until
    the infra lane adopts config.pidfile(); lanes never touch /tmp (§d)."""
    return Path('/tmp/raphael-brain.pid') if instance() == 'main' else None


def body_lock_name() -> str:
    """Windows body input-lock name (`%TMP%\\raphael_body[_<inst>].lock`)."""
    name = instance()
    return 'raphael_body.lock' if name == 'main' else f'raphael_body_{name}.lock'


def supervisor_mutex_name() -> str:
    name = instance()
    return 'Raphael_Supervisor' if name == 'main' else f'Raphael_Supervisor_{name}'


def orb_user_data_dir() -> Path:
    name = instance()
    return data_dir() / 'orb' if name != 'main' else data_dir()


def snapshot() -> Dict[str, Any]:
    """Everything derived from the instance, in one inspectable dict
    (surfaced by tests and GET /status)."""
    return {
        'instance': instance(),
        'profile': get_config().get('profile'),
        'port': port(),
        'cdp_port': cdp_port(),
        'data_dir': str(data_dir()),
        'pidfile': str(pidfile()),
        'legacy_pidfile': str(legacy_pidfile()) if legacy_pidfile() else None,
        'body_lock': body_lock_name(),
        'supervisor_mutex': supervisor_mutex_name(),
    }
