"""`report` action — Report-format delivery (PROTOCOL §7 request
docs/requests/pc-control__to__integrator__protocol-report-act.md).

ops:
* save {op, title, body, format?} — persist a Report body (findings /
  evidence / confidence / next-steps, docs/evolution/02 §3) into the FIXED
  per-user folder `Documents\\Raphael\\reports`. The model never chooses a
  path: slugified title + timestamped filename + fixed extension set, atomic
  write (.part -> replace) so a crash can never leave a half file.
* list {op} — enumerate saved reports (newest first, cap 100).

Share/open of a saved report composes from EXISTING acts (`open_path`,
`clipboard{write}`, `notify`) — no extra capability, no arbitrary writes.
`lock:false` (no input/foreground), read-only outside the reports folder.
Failure-matrix discipline (Wave 4): invalid args refused pre-side-effect,
backend errors answer truthful E_INTERNAL, result is structural.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Dict

try:
    from .actions import (offload,
ActionError, opt_enum, reject_extra, register_action,
                          req_str
)
except ImportError:  # script mode
    from actions import (offload, ActionError, opt_enum, reject_extra, register_action,
                         req_str)

_OPS = {'save', 'list'}
_FORMATS = {'md', 'txt', 'json'}
_MAX_TITLE = 120
_MAX_BODY = 400000          # well under the 8 MiB frame cap (PROTOCOL §1)
_LIST_CAP = 100
_SLUG_RE = re.compile(r'[^a-z0-9]+')


def _validate_report(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'op', 'title', 'body', 'format'})
    op = opt_enum(args, 'op', _OPS)
    if op == 'list':
        if 'title' in args or 'body' in args or 'format' in args:
            raise ValueError("op 'list' takes no title/body/format")
        return {'op': 'list'}

    title = req_str(args, 'title', max_len=_MAX_TITLE)
    body = req_str(args, 'body', max_len=_MAX_BODY, min_len=1)
    fmt = opt_enum(args, 'format', _FORMATS, default='md')
    if fmt == 'json':
        try:
            json.loads(body)
        except ValueError:
            # never echo the body (content stays out of logs/errors)
            raise ValueError("field 'body' is not valid JSON for format 'json'")
    return {'op': 'save', 'title': title, 'body': body, 'format': fmt}


def _slug(title: str) -> str:
    slug = _SLUG_RE.sub('-', title.lower()).strip('-')
    return slug[:60] or 'report'


def _unique_path(directory: Path, stem: str, ext: str) -> Path:
    candidate = directory / ('%s.%s' % (stem, ext))
    n = 2
    while candidate.exists():
        candidate = directory / ('%s-%d.%s' % (stem, n, ext))
        n += 1
    return candidate


async def _run_report(args: Dict[str, Any], backend) -> Any:
    directory = Path(await offload(backend.reports_dir))
    if args['op'] == 'list':
        entries = []
        if directory.is_dir():
            for p in directory.iterdir():
                if p.suffix.lower() not in ('.md', '.txt', '.json'):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                entries.append({'name': p.name, 'bytes': st.st_size,
                                'mtime': int(st.st_mtime * 1000)})
        entries.sort(key=lambda e: e['mtime'], reverse=True)
        total = len(entries)
        entries = entries[:_LIST_CAP]
        return {'count': total, 'reports': entries,
                **({'truncated': True} if total > len(entries) else {})}

    # ---- save: atomic, fixed directory, crash-safe --------------------
    def _write() -> Dict[str, Any]:
        directory.mkdir(parents=True, exist_ok=True)
        stem = '%s-%s' % (time.strftime('%Y%m%d-%H%M%S'),
                          _slug(args['title']))
        target = _unique_path(directory, stem, args['format'])
        tmp = target.parent / (target.name + '.part')
        data = args['body']
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(data)
            fh.flush()
        tmp.replace(target)          # atomic within the same directory
        return {'path': str(target), 'name': target.name,
                'bytes': len(data.encode('utf-8')),
                'lines': data.count('\n') + 1}

    return await offload(_write)


register_action('report', _run_report, validate=_validate_report,
                needs_lock=False, confirm=None,
                describe='Deliver a Report-format output: save into the fixed '
                         'Documents\\Raphael\\reports folder or list saved '
                         'reports (never an arbitrary path).')
