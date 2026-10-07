"""pc tool group: fixed PowerShell registry (act_req: powershell).

PROTOCOL §7/§11: only script_ids registered in body/win/act_powershell.py
can run — arbitrary command strings never cross the wire. The tool is
risky=True with confirm category `system_settings_change` (all scripts are
query-only today, but the gate stays on so new scripts cannot slip in
unconfirmed without a deliberate spec change)."""
from __future__ import annotations

from ._spec import ToolSpec, prop_string, spec

SPECS = (
    spec(
        'powershell',
        'Run a registered read-only/system PowerShell script on the PC '
        '(fixed script_id — no free-form commands). Available script_ids: '
        'list_uwp_apps (installed Start/UWP apps), disk_usage (used/free '
        'bytes per drive), network_info (IPv4 addresses), sysinfo (OS/RAM/'
        'uptime/user), recycle_bin_status (item count), notify_toast (toast '
        'notification; prefer the notify tool). Each script accepts only '
        'its declared args (currently none beyond notify_toast.text). '
        'Confirmation required before running.',
        {'script_id': prop_string('Registered script id, e.g. "disk_usage".'),
         'args': {'type': 'object',
                  'description': 'Script arguments — only keys declared by '
                                 'the script are accepted (currently only '
                                 'notify_toast takes {text}).',
                  'properties': {
                      'text': prop_string('Notification text (notify_toast '
                                          'only), 1-500 chars.'),
                  },
                  'required': [],
                  'additionalProperties': False}},
        ('script_id',),
        risky=True,
        confirm='system_settings_change',
    ),
)
