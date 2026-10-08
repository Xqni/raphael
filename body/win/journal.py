"""F-3 undoable-act journal (audit 2026-10-07 — CO-SHARE with orb).

Records UNDOABLE state changes made through act_req and can invert them.
This module + its schema are the pc-control half of the F-3 co-share; the
orb renders the viewer (docs/requests/pc-control__to__orb__activity-viewer-
schema.md) and brain-core relays queries (…__brain-core__activity-endpoint).

SCHEMA (append-only JSONL at instance.activity_log_path()):
  record    {"seq": int, "ts": ms, "kind": "volume|brightness|window|
             media|recycle_move", "act": str, "job": str|null, "summary": str,
             "inverse": {...}, "undone": false, "id": str|null,
             "undo": {"action":"activity","args":{"op":"undo","seq":N}}}
  undo      {"seq": int, "ts": ms, "undo_of": int, "job": str|null,
             "kind": str, "ok": bool, "error"?: str}
`kind` is an open enum: volume/brightness/window/media are produced today;
`recycle_move` is reserved (a producer needs its own §7 act + confirm
`delete_files` — no delete act exists in pc-control's allow-list).
`id` is the orb-viewer key (stable across restarts: stored once in BOTH the
action log and this journal, never recomputed).

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
_entry_id: Optional[str] = None
_loaded_path: Optional[str] = None
_INVERSES: Dict[str, Callable[[Dict[str, Any], Any], None]] = {}


# ------------------------------------------------------------ job context --
def set_context(job: Optional[str], entry_id: Optional[str] = None) -> None:
    """Dispatch tags every act with its job AND stable entry id (body handles
    one act_req at a time — the receive loop is sequential — so plain module
    globals are safe here). journal records + the §7 action log embed the
    same id so the orb viewer can join them."""
    global _job, _entry_id
    _job = job
    _entry_id = entry_id


def reset() -> None:
    """Tests: forget memory view + hydration cache (file untouched)."""
    global _entries, _seq, _job, _entry_id, _loaded_path
    _entries, _seq, _job, _entry_id, _loaded_path = [], 0, None, None, None


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
                if rec.get('ok') is False:
                    # failed attempt (orb undo_ok): state unchanged
                    e['undo_ok'] = False
                    e['undo_error'] = str(rec.get('error') or '')[:120]
                else:
                    e['undone'] = True
                    e['undo_ok'] = True
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
             'inverse': inverse, 'undone': False,
             # orb-viewer contract (docs/requests/orb__to__pc-control__
             # act-journal-schema): stable id + replayable undo payload.
             'id': _entry_id,
             'undo': {'action': 'activity',
                      'args': {'op': 'undo', 'seq': _seq}}}
    _entries.append(entry)
    if len(_entries) > MAX_ENTRIES:
        del _entries[:len(_entries) - MAX_ENTRIES]
    _append(entry)
    return dict(entry)


def entries(limit: int = 20) -> List[Dict[str, Any]]:
    """Newest-first view with undone flags folded in."""
    _ensure_loaded()
    return [dict(e) for e in list(reversed(_entries))[:max(1, int(limit))]]


def resolve_id(entry_id: str) -> int:
    """orb REST gives us an `id`; the executor works on `seq`."""
    _ensure_loaded()
    for e in _entries:
        if e.get('id') == entry_id:
            return int(e['seq'])
    raise UndoError('no journal entry with id %s' % str(entry_id)[:40])


def undo(seq: Optional[int] = None, backend: Any = None,
         entry_id: Optional[str] = None) -> Dict[str, Any]:
    """Undo a specific entry (by seq OR stable id, or the newest undoable
    one). Applies the inverse FIRST; success marks undone + appends an
    `ok:true` marker; failure appends an `ok:false` marker (orb `undo_ok`)
    and re-raises — the journal never lies about state."""
    _ensure_loaded()
    if entry_id is not None:
        seq = resolve_id(entry_id)
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
    global _seq
    try:
        handler(target, backend)             # raises UndoError/BackendError
    except Exception as e:
        _seq += 1
        _append({'seq': _seq, 'ts': int(time.time() * 1000),
                 'undo_of': target['seq'], 'job': _job,
                 'kind': target['kind'], 'ok': False,
                 'error': str(e)[:120]})
        target['undo_ok'] = False            # in-memory view must match too
        target['undo_error'] = str(e)[:120]
        raise
    target['undone'] = True
    target['undo_ok'] = True
    _seq += 1
    marker = {'seq': _seq, 'ts': int(time.time() * 1000),
              'undo_of': target['seq'], 'job': _job, 'kind': target['kind'],
              'ok': True}
    target['undo_seq'] = marker['seq']
    _append(marker)
    return dict(target)


def log_entries(limit: int = 30) -> List[Dict[str, Any]]:
    """ORB-SCHEMA full activity view (agreement in docs/requests/orb__
    to__pc-control__act-journal-schema.md): one row PER executed act from
    the §7 action log, joined with this journal's reversibility overlay.

    Row shape (superset of both stores, read-only for the viewer):
      {id, ts, job, action, args, ok, error, summary, reversible, undo,
       undone, undo_ok}
    `id` is null for rows logged before ids existed -> reversible:false,
    undo:null (the viewer must not offer an unresolvable undo)."""
    _ensure_loaded()
    try:
        raw = instance.action_log_path().read_text(encoding='utf-8')
    except OSError:
        raw = ''
    rows = []
    for line in raw.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    overlay = {e.get('id'): e for e in _entries if e.get('id')}
    out: List[Dict[str, Any]] = []
    for row in reversed(rows):                  # newest first
        if len(out) >= max(1, int(limit)):
            break
        rid = row.get('id')
        j = overlay.get(rid)
        undone = bool(j and j.get('undone'))
        reversible = j is not None
        summary = ((j or {}).get('summary')
                   or ('%s ok' % row.get('action') if row.get('ok')
                       else '%s failed' % row.get('action')))
        out.append({
            'id': rid,
            'ts': row.get('ts'),
            'job': row.get('job'),
            'action': row.get('action'),
            'args': row.get('args'),
            'ok': bool(row.get('ok')),
            'error': row.get('error'),
            'summary': str(summary)[:80],
            'reversible': reversible,
            'undo': None if (not reversible or undone) else j.get('undo'),
            'undone': undone,
            'undo_ok': (j.get('undo_ok') if j else None),
        })
    return out


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


def _inverse_media(entry: Dict[str, Any], backend) -> None:
    """Toggle-style media undo: play_pause -> play_pause, mute -> mute
    (agreed default-rule row; next/prev/stop are NOT journaled)."""
    if backend is None:
        raise UndoError('no backend for media undo')
    backend.media_key(str(entry['inverse']['op']))


register_inverse('volume', _inverse_volume)
register_inverse('brightness', _inverse_brightness)
register_inverse('window', _inverse_window)
register_inverse('media', _inverse_media)
# 'recycle_move' intentionally NOT registered: no producer act exists yet
# (would need its own §7 approval + confirm category delete_files).
