"""Golden-transcript normalization + comparison (wave-3 transcripts).

Volatile fields are stripped/replaced so goldens stay stable across runs:
- `ts`, `expires_at`            -> dropped (clocks)
- `session`                     -> '<sid>'
- auth `token`                  -> '<token>' (never store credentials)
- `job` ids (`j_YYYYMMDD_NNNN`) -> j_1, j_2, ... by first appearance
- `server_v`                    -> '<server_v>' (bumps are not regressions)

Comparison contract (broadcast scheduling makes cross-frame ordering racy):
- per-session SENT frames: exact ordered list equality (test code = deterministic)
- per-session RECV frames: MULTISET equality (sorted normalized JSON) —
  catches missing/extra/changed frames;
- PLUS ordered `job_event.status` chain per job (queued->...->terminal must
  keep protocol order — the part that IS deterministic).
"""
from __future__ import annotations

import copy
import json
from typing import Dict, List

VOLATILE_DROP = ('ts', 'expires_at')


def normalize(frames: List[dict], job_map: Dict[str, str]) -> List[dict]:
    out = []
    for fr in frames:
        f = copy.deepcopy(fr)
        for k in VOLATILE_DROP:
            f.pop(k, None)
        if 'session' in f:
            f['session'] = '<sid>'
        if 'server_v' in f:
            f['server_v'] = '<server_v>'
        if f.get('type') == 'auth' and 'token' in f:
            f['token'] = '<token>'
        _remap_jobs(f, job_map)
        out.append(f)
    return out


def _new_job(v: str, job_map: Dict[str, str]) -> str:
    if v not in job_map:
        job_map[v] = f'j_{len(job_map) + 1}'
    return job_map[v]


def _remap_jobs(obj, job_map):
    if isinstance(obj, dict):
        for key in ('job', 'parent'):
            v = obj.get(key)
            if isinstance(v, str) and v.startswith('j_'):
                obj[key] = _new_job(v, job_map)
        inner = obj.get('job')
        if isinstance(inner, dict) and isinstance(inner.get('job'), str):
            inner['job'] = _new_job(inner['job'], job_map)
    # nested lists (job_list['jobs'])
    if isinstance(obj, list):
        for item in obj:
            _remap_jobs(item, job_map)


def normalize_session(session: dict) -> dict:
    """One session record {sent, recv} -> normalized (shared job_map)."""
    job_map: Dict[str, str] = {}
    sent = normalize(session.get('sent', []), job_map)
    recv = normalize(session.get('recv', []), job_map)
    return {'sent': sent, 'recv': recv}


def snapshot_normalize(snap: Dict[str, dict]) -> Dict[str, dict]:
    """Whole-scenario snapshot (label -> {sent,recv}) with ONE shared job_map
    across sessions so ids align between golden and replay."""
    job_map: Dict[str, str] = {}
    out = {}
    for label in sorted(snap):
        s = snap[label]
        out[label] = {
            'sent': normalize(s.get('sent', []), job_map),
            'recv': normalize(s.get('recv', []), job_map),
        }
    return out


def multiset(frames: List[dict]) -> List[str]:
    return sorted(json.dumps(f, sort_keys=True, ensure_ascii=False)
                  for f in frames)


def job_status_chains(snap: Dict[str, dict]) -> Dict[str, List[str]]:
    """job -> ordered terminal-relevant statuses across all sessions."""
    chains: Dict[str, List[str]] = {}
    for label in sorted(snap):
        for f in snap[label]['recv']:
            if f.get('type') == 'job_event' and f.get('job'):
                chain = chains.setdefault(f['job'], [])
                st = f.get('status')
                if not chain or chain[-1] != st:
                    chain.append(st)
    return chains


def compare(golden: dict, replayed: dict) -> List[str]:
    """-> list of human-readable mismatches (empty = pass)."""
    problems = []
    if sorted(golden) != sorted(replayed):
        return [f'session labels differ: golden={sorted(golden)} '
                f'replayed={sorted(replayed)}']
    for label in sorted(golden):
        g, r = golden[label], replayed[label]
        if g['sent'] != r['sent']:
            problems.append(f'{label}: sent frames differ\n'
                            f'  golden={g["sent"]}\n  replay={r["sent"]}')
        if multiset(g['recv']) != multiset(r['recv']):
            only_g = [x for x in multiset(g['recv'])
                      if multiset(g['recv']).count(x) >
                      multiset(r['recv']).count(x)]
            only_r = [x for x in multiset(r['recv'])
                      if multiset(r['recv']).count(x) >
                      multiset(g['recv']).count(x)]
            problems.append(f'{label}: recv multiset differs\n'
                            f'  only-golden({len(only_g)}): {only_g[:3]}\n'
                            f'  only-replay({len(only_r)}): {only_r[:3]}')
    gc, rc = job_status_chains(golden), job_status_chains(replayed)
    if gc != rc:
        problems.append(f'job status chains differ: golden={gc} replay={rc}')
    return problems


def load_golden(path) -> dict:
    doc = json.loads(path.read_text(encoding='utf-8'))
    return doc['sessions']
