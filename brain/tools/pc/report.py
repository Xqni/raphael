"""pc tool group: Report-format delivery (act_req: report).

Save a Report body into the fixed `Documents\\Raphael\\reports` folder or
list saved reports. The model NEVER supplies a path (fixed dir + slugified
title). Sharing/opening composes from existing tools: `open_path`,
`clipboard` (write), `notify`.
"""
from __future__ import annotations

from ._spec import ToolSpec, prop_enum, prop_int, prop_string, spec

SPECS = (
    spec(
        'report',
        'Deliver a Report-format output (Analysis/evolution reports: '
        'findings, evidence file:line, confidence, next steps). op=save '
        'writes the body into the FIXED folder '
        'Documents\\Raphael\\reports with a slugified timestamped filename '
        '(you never choose a path) and returns the saved path; op=list '
        'enumerates saved reports (newest first). To SHARE afterwards: open '
        'the path with open_path, or copy it with clipboard, or announce it '
        'with notify. format=json validates that the body parses as JSON.',
        {'op': prop_enum('save = write a report, list = enumerate saved '
                         'reports.', ['save', 'list']),
         'title': prop_string('Report title, 1-120 chars — becomes the '
                              'filename slug (required for op=save).'),
         'body': prop_string('Full report text, 1-400000 chars (required for '
                             'op=save). Markdown by default.'),
         'format': prop_enum('File extension/format for op=save (default md).',
                             ['md', 'txt', 'json'])},
        ('op',),
    ),
)
