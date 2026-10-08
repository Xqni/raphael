"""F-3 undoable-act journal (audit 2026-10-07 — CO-SHARE with orb).

Records UNDOABLE state changes made through act_req and can invert them.
This module + its schema are the pc-control half of the F-3 co-share; the
orb renders the viewer (docs/requests/pc-control__to__orb__activity-viewer-
schema.md) and brain-core relays queries (…__brain-core__activity-endpoint).

SCHEMA (append-only JSONL at instance.activity_log_path()):
  record    {"seq": int, "ts": ms, "kind": "volume|brightness|window|
             recycle_move", "act": str, "job": str|null, "summary": str,
             "inverse": {...}, "undone": false}
  undo      {"seq": int, "ts": ms, "undo_of": int, "job": str|null,
             "kind": str}
`kind` is an open enum: volume/brightness/window are produced today;
`recycle_move` is reserved (a producer needs its own §7 act + confirm
`delete_files` — no delete act exists in pc-control's allow-list).

Guarantees:
* inverse is captured BEFORE the mutation; recorded only AFTER success;
* undo applies the inverse first and marks undone only on success (a failed
  undo raises — the journal never lies about state);
* file writes are best-effort: a journal I/O failure never fails the act
  (loud print, memory view kept);
* confirmations are untouched (AGENT_RULES §8): journaling adds no bypass —
  acts keep their existing risky/confirm metadata in brain/tools/pc.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional

try:
    from . import instance
except ImportError:          # script mode (body/win on sys.path)
    import instance

MAX_ENTRIES = 500            # in-memory view cap (file keeps full history)
LOG_MAX_BYTES = 5 * 1024 * 1024


class UndoError(RuntimeError):
    """Inverse could not be applied — nothing is marked undone."""


_entries: List[Dict[str, Any]] = []
_seq = 0
_job: Optional[str] = None
_loaded_path: Optional[str] = None
_INVERSES: Dict[str, Callable[[Dict[str, Any], Any], None]] = {}


# ------------------------------------------------------------ job context --
def set_job(job: Optional[str]) -> None:
    """Dispatch tags every act with its job (body handles one act_req at a
    time — the receive loop is sequential — so a plain module global is
    safe here)."""
    global _job
    _job = job


def reset() -> None:
    """Tests: forget memory view + hydration cache (file untouched)."""
    global _entries, _seq, _job, _loaded_path
    _entries, _seq, _job, _loaded_path = [], 0, None, None


def register_inverse(kind: str,
                     fn: Callable[[Dict[str, Any], Any], None]) -> None:
    _INVERSES[kind] = fn


# ---------------------------------------------------------------- storage --
def _append(line: Dict[str, Any]) -> None:
    try:
        path = instance.activity_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > LOG_MAX_BYTES:
            backup = path.with_suffix(path.suffix + '.1')
            backup.unlink(missing_ok=True)
            path.replace(backup)
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + '\n')
    except OSError as e:                    # best-effort, never fails the act
        print('[journal] activity-log write failed: %s' % e, flush=True)


def _ensure_loaded() -> None:
    global _entries, _seq, _loaded_path
    path = str(instance.activity_log_path())
    if _loaded_path == path:
        return
    _entries, _seq = [], 0
    _loaded_path = path
    try:
        raw = (instance.activity_log_path()).read_text(encoding='utf-8')
    except OSError:
        return
    for line in raw.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        _absorb(rec)


def _absorb(rec: Dict[str, Any]) -> None:
    global _seq
    if 'undo_of' in rec:
        for e in _entries:
            if e['seq'] == rec['undo_of']:
                e['undone'] = True
                e['undo_seq'] = rec.get('seq')
        return
    if 'seq' in rec and 'kind' in rec:
        rec.setdefault('undone', False)
        _entries.append(rec)
        _seq = max(_seq, int(rec.get('seq') or 0))


# ------------------------------------------------------------------ public --
def record(kind: str, act: str, summary: str,
           inverse: Dict[str, Any]) -> Dict[str, Any]:
    """Append an undoable record (in-memory + JSONL). Never raises."""
    global _entries, _seq
    _ensure_loaded()
    _seq += 1
    entry = {'seq': _seq, 'ts': int(time.time() * 1000), 'kind': kind,
             'act': act, 'job': _job, 'summary': summary,
             'inverse': inverse, 'undone': False}
    _entries.append(entry)
    if len(_entries) > MAX_ENTRIES:
        del _entries[:len(_entries) - MAX_ENTRIES]
    _append(entry)
    return dict(entry)


def entries(limit: int = 20) -> List[Dict[str, Any]]:
    """Newest-first view with undone flags folded in."""
    _ensure_loaded()
    return [dict(e) for e in list(reversed(_entries))[:max(1, int(limit))]]


def undo(seq: Optional[int] = None, backend: Any = None) -> Dict[str, Any]:
    """Undo a specific entry (or the newest undoable one). Applies the
    inverse FIRST; only a successful apply marks the entry undone and
    appends the undo marker. Raises UndoError when nothing applies."""
    _ensure_loaded()
    target = None
    if seq is None:
        for e in reversed(_entries):
            if not e.get('undone') and e.get('kind') in _INVERSES:
                target = e
                break
    else:
        target = next((e for e in _entries if e.get('seq') == int(seq)), None)
        if target is None:
            raise UndoError('no journal entry with seq %s' % seq)
        if target.get('undone'):
            raise UndoError('entry %s is already undone' % seq)
    if target is None:
        raise UndoError('nothing to undo')
    handler = _INVERSES.get(target.get('kind'))
    if handler is None:
        raise UndoError("kind '%s' has no inverse handler" % target.get('kind'))
    handler(target, backend)                 # raises UndoError/BackendError
    target['undone'] = True
    global _seq
    _seq += 1
    marker = {'seq': _seq, 'ts': int(time.time() * 1000),
              'undo_of': target['seq'], 'job': _job, 'kind': target['kind']}
    target['undo_seq'] = marker['seq']
    _append(marker)
    return dict(target)


# ------------------------------------------------- built-in inverse ops ----
def _inverse_volume(entry: Dict[str, Any], backend) -> None:
    level = int(entry['inverse']['level'])
    if backend is None:
        raise UndoError('no backend for volume undo')
    if not backend.set_volume(level):
        raise UndoError('volume restore to %d failed' % level)


def _inverse_brightness(entry: Dict[str, Any], backend) -> None:
    level = int(entry['inverse']['level'])
    if backend is None:
        raise UndoError('no backend for brightness undo')
    if not backend.set_brightness(level):
        raise UndoError('brightness restore to %d failed' % level)


def _inverse_window(entry: Dict[str, Any], backend) -> None:
    if backend is None:
        raise UndoError('no backend for window undo')
    inv = entry['inverse']
    backend.set_placement(int(inv['hwnd']), dict(inv['placement']))


register_inverse('volume', _inverse_volume)
register_inverse('brightness', _inverse_brightness)
register_inverse('window', _inverse_window)
# 'recycle_move' intentionally NOT registered: no producer act exists yet
# (would need its own §7 approval + confirm category delete_files).
