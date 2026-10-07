"""Self-written skills — SKILL.md loader with draft state, confidence gate,
usage counters and dedup (addendum §4, Odysseus skills layer).

Truth model:
- the FILE `skills/<name>/SKILL.md` is the source of truth for content and
  frontmatter (git-tracked → the USER reviews what Raphael learned);
- `skills_index` mirrors it for listing + owns the SIDECAR counters
  (`uses`, `last_used`, `dedup_hits`) that must survive file rewrites.

THE CONFIDENCE GATE (prompt-injection defense): only
`status == 'published' AND confidence >= skills.gate_confidence` ever come
back from `active_skills()` — drafts and low-confidence skills are listable
for review but NEVER auto-injected (drafts start at 0.0 / status=draft).

Safety: skill names are strict `[a-z0-9_-]` (path-traversal defense), files
are parsed with `yaml.safe_load`, creation dedups at Jaccard >= gate instead
of duplicating, and every reader is fail-silent (a broken index must not
break a turn).
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

NAME_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
STATUSES = ('draft', 'published')
SOURCES = ('learned', 'taught', 'created')
_SECTIONS = ('## When to Use', '## Procedure', '## Pitfalls', '## Verification')


class SkillError(ValueError):
    """Malformed skill (frontmatter/name/status/confidence) — loud on
    parse/create, recorded-not-raised on sync."""


def _cfg(dotted: str, default: Any) -> Any:
    try:
        from .. import config as appcfg
        return appcfg.cfg_get(appcfg.get_config(), dotted, default)
    except Exception:  # noqa: BLE001
        return default


def skills_dir() -> Path:
    raw = str(_cfg('skills.dir', 'skills') or 'skills')
    p = Path(raw).expanduser()
    if not p.is_absolute():
        from .. import config as appcfg
        p = appcfg.REPO_ROOT / p
    return p


def _tokens(text: Any) -> set:
    return set(re.findall(r'[a-z0-9]+', str(text or '').lower()))


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    return (len(a & b) / union) if union else 0.0


def _split(text: str) -> Tuple[Dict[str, Any], str]:
    """Frontmatter dict + body. Raises SkillError when malformed."""
    import yaml
    if not text.startswith('---'):
        raise SkillError('missing YAML frontmatter (must start with ---)')
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n?', text, re.DOTALL)
    if not m:
        raise SkillError('unterminated frontmatter')
    try:
        meta = yaml.safe_load(m.group(1))
    except Exception as e:  # noqa: BLE001 — yaml is untrusted input
        raise SkillError(f'bad YAML frontmatter: {type(e).__name__}')
    if not isinstance(meta, dict):
        raise SkillError('frontmatter must be a mapping')
    body = text[m.end():]
    return meta, body


def _validate(meta: Dict[str, Any], body: str) -> Dict[str, Any]:
    name = str(meta.get('name') or '')
    if not NAME_RE.match(name):
        raise SkillError(f'invalid skill name {name!r} (need {NAME_RE.pattern})')
    status = str(meta.get('status') or 'draft')
    if status not in STATUSES:
        raise SkillError(f'invalid status {status!r} (one of {STATUSES})')
    source = str(meta.get('source') or 'learned')
    if source not in SOURCES:
        raise SkillError(f'invalid source {source!r} (one of {SOURCES})')
    raw_conf = meta.get('confidence')
    if isinstance(raw_conf, bool):         # `confidence: true` must not = 1.0
        raise SkillError(f'invalid confidence {raw_conf!r} (boolean)')
    try:
        confidence = float(raw_conf or 0.0)
    except (TypeError, ValueError):
        raise SkillError(f'invalid confidence {raw_conf!r}')
    if not 0.0 <= confidence <= 1.0:
        raise SkillError(f'confidence {confidence} outside [0, 1]')
    tags = meta.get('tags') or []
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        raise SkillError('tags must be a list')
    return {
        'name': name,
        'description': str(meta.get('description') or ''),
        'version': str(meta.get('version') or '1'),
        'category': str(meta.get('category') or 'general'),
        'tags': [str(t) for t in tags],
        'status': status,
        'confidence': round(confidence, 4),
        'source': source,
        'created': str(meta.get('created') or time.strftime('%Y-%m-%d')),
        'body': str(body or ''),
        'content_hash': hashlib.sha256(
            text_hash_src(meta, body).encode('utf-8')).hexdigest(),
    }


def text_hash_src(meta: Dict[str, Any], body: str) -> str:
    """Stable hash input: name + description + body (meta minus volatile keys
    like `created` still counts via name/description which define identity)."""
    return f"{meta.get('name','')}|{meta.get('description','')}|{body}"


def parse_skill(text: str) -> Dict[str, Any]:
    """Parse a full SKILL.md into a validated record. Raises SkillError."""
    meta, body = _split(str(text or ''))
    return _validate(meta, body)


def _render(record: Dict[str, Any]) -> str:
    """Record -> SKILL.md file content (frontmatter + body)."""
    import yaml
    fm = {
        'name': record['name'],
        'description': record.get('description', ''),
        'version': record.get('version', '1'),
        'category': record.get('category', 'general'),
        'tags': list(record.get('tags') or []),
        'status': record.get('status', 'draft'),
        'confidence': float(record.get('confidence') or 0.0),
        'source': record.get('source', 'learned'),
        'created': record.get('created') or time.strftime('%Y-%m-%d'),
    }
    dump = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
    body = record.get('body', '')
    sections = '' if not body else ('\n' if body.startswith('\n') else '')
    return f'---\n{dump}---\n{sections}{body}'


def _upsert_row(record: Dict[str, Any], path: str) -> None:
    """Mirror content fields; KEEP sidecar counters on update."""
    from . import get_conn
    conn = get_conn()
    try:
        row = conn.execute('SELECT name FROM skills_index WHERE name = ?',
                           (record['name'],)).fetchone()
        now = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
        if row is None:
            conn.execute(
                'INSERT INTO skills_index (name, path, description, category, '
                'tags, status, confidence, source, content_hash, created_at, '
                'updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (record['name'], path, record['description'],
                 record['category'], json.dumps(record['tags']),
                 record['status'], record['confidence'], record['source'],
                 record['content_hash'], now, now))
        else:
            conn.execute(
                'UPDATE skills_index SET path=?, description=?, category=?, '
                'tags=?, status=?, confidence=?, source=?, content_hash=?, '
                'updated_at=? WHERE name=?',
                (path, record['description'], record['category'],
                 json.dumps(record['tags']), record['status'],
                 record['confidence'], record['source'],
                 record['content_hash'], now, record['name']))
        conn.commit()
    finally:
        conn.close()


def sync(*, directory: Optional[Path] = None) -> Dict[str, Any]:
    """Scan skills/<name>/SKILL.md, validate each, mirror to the index.
    Never raises: malformed files are counted + returned in `errors`."""
    out: Dict[str, Any] = {'loaded': 0, 'invalid': 0, 'errors': {}}
    try:
        d = Path(directory) if directory else skills_dir()
        if not d.is_dir():
            return out
        for md in sorted(d.glob('*/SKILL.md')):
            try:
                rec = parse_skill(md.read_text(encoding='utf-8'))
                _upsert_row(rec, str(md))
                out['loaded'] += 1
            except Exception as e:  # noqa: BLE001 — one bad file != no skills
                out['invalid'] += 1
                out['errors'][str(md)] = f'{type(e).__name__}: {e}'
    except Exception as e:  # noqa: BLE001
        out['errors']['<scan>'] = f'{type(e).__name__}: {e}'
    return out


def create_skill(name: str, description: str, body: str, *,
                 category: str = 'general', tags: Tuple = (),
                 source: str = 'learned', confidence: float = 0.0,
                 status: str = 'draft',
                 directory: Optional[Path] = None) -> str:
    """Write a new skill (draft by default) — or DEDUP into an existing one.

    Dedup: Jaccard over normalized tokens of `description + body` vs every
    existing skill >= `skills.dedup_jaccard` (0.82) → no new file; the match
    gets `dedup_hits + 1` and `uses + 1`. Returns the resulting skill name.
    Raises SkillError on invalid name/status/source/confidence."""
    name = str(name or '').strip()
    if not NAME_RE.match(name):
        raise SkillError(f'invalid skill name {name!r} (need {NAME_RE.pattern})')
    if status not in STATUSES:
        raise SkillError(f'invalid status {status!r}')
    if source not in SOURCES:
        raise SkillError(f'invalid source {source!r}')
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise SkillError(f'confidence {confidence} outside [0, 1]')
    description = str(description or '').strip()
    body = str(body or '')
    if not description and not body.strip():
        raise SkillError('skill needs a description or body')

    d = Path(directory) if directory else skills_dir()
    gate = float(_cfg('skills.dedup_jaccard', 0.82) or 0.82)

    # ---- dedup against existing skills (file bodies are the truth) --------
    new_tokens = _tokens(description + '\n' + body)
    for existing in _list_rows():
        try:
            rec = get_skill(existing['name'], directory=d)
            if not rec:
                continue
            if jaccard(new_tokens, _tokens(rec['description'] + '\n' + rec['body'])) >= gate:
                _bump(existing['name'], uses=1, dedup=1)
                return existing['name']
        except Exception:  # noqa: BLE001 — unreadable candidate: skip it
            continue

    record = {
        'name': name, 'description': description, 'version': '1',
        'category': str(category or 'general'), 'tags': [str(t) for t in tags],
        'status': status, 'confidence': round(confidence, 4),
        'source': source, 'created': time.strftime('%Y-%m-%d'),
        'body': body, 'content_hash': hashlib.sha256(
            f'{name}|{description}|{body}'.encode('utf-8')).hexdigest(),
    }
    path = d / name / 'SKILL.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(record), encoding='utf-8')
    _upsert_row(record, str(path))
    return name


def _list_rows() -> List[Dict[str, Any]]:
    from . import get_conn
    conn = get_conn()
    try:
        rows = conn.execute(
            'SELECT name, path, description, category, tags, status, '
            'confidence, source, uses, last_used, dedup_hits, created_at '
            'FROM skills_index '
            'ORDER BY name').fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_skills() -> List[Dict[str, Any]]:
    """All indexed skills (review listing). Fail-silent: errors -> []."""
    try:
        return _list_rows()
    except Exception:  # noqa: BLE001
        return []


def get_skill(name: str, *, directory: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Full record incl. body (file truth). None if missing/unreadable."""
    try:
        if not NAME_RE.match(str(name or '')):
            return None
        d = Path(directory) if directory else skills_dir()
        md = d / name / 'SKILL.md'
        if not md.is_file():
            return None
        return parse_skill(md.read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return None


def active_skills(*, min_confidence: Optional[float] = None) -> List[Dict[str, Any]]:
    """THE GATE: skills safe to auto-inject — published AND confidence above
    `skills.gate_confidence` (drafts excluded unless `skills.inject_drafts`).
    Fail-silent: errors -> []. Never returns draft/low-confidence rows
    unless explicitly configured to."""
    try:
        gate = float(min_confidence if min_confidence is not None
                     else _cfg('skills.gate_confidence', 0.6) or 0.0)
        inject_drafts = bool(_cfg('skills.inject_drafts', False))
        from . import get_conn
        conn = get_conn()
        try:
            if inject_drafts:
                rows = conn.execute(
                    'SELECT name, description, category, tags, status, '
                    'confidence, source, uses FROM skills_index '
                    'WHERE confidence >= ? ORDER BY uses DESC, name',
                    (gate,)).fetchall()
            else:
                rows = conn.execute(
                    'SELECT name, description, category, tags, status, '
                    'confidence, source, uses FROM skills_index '
                    "WHERE status = 'published' AND confidence >= ? "
                    'ORDER BY uses DESC, name',
                    (gate,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return []


def bump_skill_use(name: str) -> None:
    """Called when a skill is actually included in a prompt / reused.
    Fail-silent."""
    try:
        _bump(name, uses=1, dedup=0)
    except Exception:  # noqa: BLE001
        pass


def _bump(name: str, *, uses: int = 0, dedup: int = 0) -> None:
    from . import get_conn
    conn = get_conn()
    try:
        conn.execute(
            'UPDATE skills_index SET uses = uses + ?, dedup_hits = dedup_hits + ?, '
            'last_used = ? WHERE name = ?',
            (int(uses), int(dedup),
             time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime()), name))
        conn.commit()
    finally:
        conn.close()


def _set_meta(name: str, **fields: Any) -> bool:
    """Update frontmatter fields in BOTH file and index (no drift between
    the two sources of truth). Returns False when the skill is missing."""
    rec = get_skill(name)
    if rec is None:
        return False
    for k, v in fields.items():
        if k == 'confidence':
            if isinstance(v, bool):         # True must not coerce to 1.0
                raise SkillError(f'invalid confidence {v!r} (boolean)')
            v = float(v)
            if not 0.0 <= v <= 1.0:
                raise SkillError(f'confidence {v} outside [0, 1]')
        if k == 'status' and v not in STATUSES:
            raise SkillError(f'invalid status {v!r}')
        rec[k] = v
    rec['content_hash'] = hashlib.sha256(
        f"{rec['name']}|{rec['description']}|{rec['body']}".encode('utf-8')).hexdigest()
    path = Path(_row_path(name) or (skills_dir() / name / 'SKILL.md'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(rec), encoding='utf-8')
    _upsert_row(rec, str(path))
    return True


def _row_path(name: str) -> Optional[str]:
    from . import get_conn
    conn = get_conn()
    try:
        row = conn.execute('SELECT path FROM skills_index WHERE name = ?',
                           (name,)).fetchone()
        return str(row['path']) if row else None
    finally:
        conn.close()


def set_status(name: str, status: str) -> bool:
    """Publish/promote a skill (Wave-3 gate mechanics; promotion itself is
    Wave-5: gate pass + user approval). Fail-silent on missing skill."""
    try:
        return _set_meta(name, status=status)
    except SkillError:
        raise
    except Exception:  # noqa: BLE001
        return False


def set_confidence(name: str, confidence: float) -> bool:
    try:
        return _set_meta(name, confidence=confidence)
    except SkillError:
        raise
    except Exception:  # noqa: BLE001
        return False


def delete_skill(name: str) -> bool:
    """User review/delete capability (addendum §4). Removes file + row.
    Wave-4 export/delete controls build on this. Fail-silent -> False."""
    try:
        if not NAME_RE.match(str(name or '')):
            return False
        row_path = _row_path(name)
        from . import get_conn
        conn = get_conn()
        try:
            cur = conn.execute('DELETE FROM skills_index WHERE name = ?',
                               (name,))
            conn.commit()
            removed_row = bool(cur.rowcount)
        finally:
            conn.close()
        md = Path(row_path) if row_path else (skills_dir() / name / 'SKILL.md')
        file_existed = md.is_file()
        if file_existed:
            os.remove(md)
            try:
                md.parent.rmdir()          # only when now empty
            except OSError:
                pass
        return removed_row or file_existed
    except Exception:  # noqa: BLE001
        return False


# ---- wave-4: aging audit + dedup hardening ----------------------------------
def _age_days(created_at: Any) -> int:
    """Days since the index row was created (fail-silent -> 0)."""
    try:
        import datetime as _dt
        created = _dt.datetime.strptime(str(created_at)[:19],
                                         '%Y-%m-%d %H:%M:%S')
        now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
        return max(0, (now - created).days)
    except Exception:  # noqa: BLE001
        return 0


def find_duplicates(directory: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Dedup hardening: detect duplicates ALREADY on disk (two skills at/over
    the `skills.dedup_jaccard` similarity). Report-only — never auto-merges
    existing files (merging user-visible content = user's call)."""
    out: List[Dict[str, Any]] = []
    try:
        gate = float(_cfg('skills.dedup_jaccard', 0.82) or 0.82)
        rows = _list_rows()
        d = Path(directory) if directory else None
        recs = []
        for row in rows:
            rec = get_skill(row['name'], directory=d) if d else get_skill(row['name'])
            if rec:
                recs.append((row['name'],
                             _tokens(rec['description'] + '\n' + rec['body'])))
        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                sim = jaccard(recs[i][1], recs[j][1])
                if sim >= gate:
                    out.append({'a': recs[i][0], 'b': recs[j][0],
                                'similarity': round(sim, 3)})
    except Exception:  # noqa: BLE001 — audit must never raise
        return out
    return out


def audit_skills(*, grace_days: Optional[int] = None) -> Dict[str, Any]:
    """Periodic aging audit (addendum §4 demote flow): a PUBLISHED skill that
    has NEVER been used and is older than the grace window is demoted back to
    draft — it stops auto-injecting until reviewed/used again. Report-only for
    everything else; never deletes; fail-silent -> empty report on errors."""
    report: Dict[str, Any] = {'demoted': [], 'kept': [], 'duplicates': [],
                              'grace_days': None}
    try:
        grace = int(grace_days if grace_days is not None
                    else _cfg('skills.audit_grace_days', 30) or 30)
        report['grace_days'] = grace
        for row in _list_rows():
            if row.get('status') != 'published':
                report['kept'].append(row['name'])   # drafts age naturally
                continue
            age = _age_days(row.get('created_at') or row.get('last_used'))
            if int(row.get('uses') or 0) == 0 and age > grace:
                if set_status(row['name'], 'draft'):
                    report['demoted'].append(row['name'])
                else:
                    report['kept'].append(row['name'])
            else:
                report['kept'].append(row['name'])
        report['duplicates'] = find_duplicates()
        return report
    except Exception:  # noqa: BLE001 — a FAILED audit must look failed,
        return {}       # never like a clean one (empty report = error)
