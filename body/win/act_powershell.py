"""Fixed PowerShell script registry (PROTOCOL §7/§11: `powershell` actions
take a `script_id` from this registry — arbitrary command strings NEVER
cross the wire).

Contract:
* argv is a FIXED list (no shell, `shell=False` in the backend);
* script arguments are declared per script (name/type/pattern/range) and
  passed to the child via `RAPHAEL_ARG_<NAME>` environment variables — the
  script reads `$env:RAPHAEL_ARG_*`, so user text is never interpolated
  into command text (no injection surface);
* every script MUST declare its confirm category explicitly (`None` for
  read-only queries, `system_settings_change` for anything mutating) —
  validation of the registry happens at import;
* `confirm` at the `powershell` action level defaults to
  `system_settings_change` (brain/tools/pc/powershell.py declares it).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

try:
    from .actions import (offload,
ActionError, reject_extra, register_action, req_str
)
except ImportError:  # script mode
    from actions import (ActionError, reject_extra, register_action, req_str)

_POWERSHELL = ['powershell', '-NoProfile', '-NonInteractive',
               '-ExecutionPolicy', 'Bypass', '-Command']


def _cmd(body: str) -> list:
    return _POWERSHELL + [body]


# script_id -> spec. `args`: declared parameters (extra keys rejected);
# `json`: parse stdout as JSON; `array`: normalize a 1-element object to a list.
SCRIPTS: Dict[str, Dict[str, Any]] = {
    'list_uwp_apps': {
        'title': 'list installed Start/UWP apps',
        'confirm': None,               # read-only
        'timeout_s': 15.0,             # fail fast: this is open_app's last
                                       # resolution stage (Bug B / Rule 15)
        'json': True, 'array': True,
        'args': {},
        'argv': _cmd(
            "Get-StartApps | ForEach-Object { [pscustomobject]@{"
            " name = $_.Name; app_id = $_.AppID } } | ConvertTo-Json -Compress"),
        'describe': 'Installed Start-menu/UWP apps (name, app_id).',
    },
    'disk_usage': {
        'title': 'disk usage per drive',
        'confirm': None,               # read-only
        'timeout_s': 20.0,
        'json': True, 'array': True,
        'args': {},
        'argv': _cmd(
            "Get-PSDrive -PSProvider FileSystem | ForEach-Object { "
            "[pscustomobject]@{ name = $_.Name; used = $_.Used; free = $_.Free } "
            "} | ConvertTo-Json -Compress"),
        'describe': 'Used/free bytes per filesystem drive.',
    },
    'network_info': {
        'title': 'IPv4 network configuration',
        'confirm': None,               # read-only
        'timeout_s': 20.0,
        'json': True, 'array': True,
        'args': {},
        'argv': _cmd(
            "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue "
            "| Where-Object { $_.IPAddress -ne '127.0.0.1' } | ForEach-Object { "
            "[pscustomobject]@{ ip = $_.IPAddress; iface = $_.InterfaceAlias } } "
            "| ConvertTo-Json -Compress"),
        'describe': 'IPv4 addresses and interfaces (no loopback).',
    },
    'sysinfo': {
        'title': 'system info (OS, uptime, RAM, user)',
        'confirm': None,               # read-only
        'timeout_s': 20.0,
        'json': True,
        'args': {},
        'argv': _cmd(
            "$o = Get-CimInstance Win32_OperatingSystem; "
            "[pscustomobject]@{ caption = $o.Caption; version = $o.Version; "
            "last_boot = $o.LastBootUpTime.ToString('s'); "
            "total_ram_mb = [int]($o.TotalVisibleMemorySize / 1024); "
            "free_ram_mb = [int]($o.FreePhysicalMemory / 1024); "
            "user = $env:USERNAME; computer = $env:COMPUTERNAME } "
            "| ConvertTo-Json -Compress"),
        'describe': 'OS version, last boot time, RAM totals, user/computer.',
    },
    'recycle_bin_status': {
        'title': 'recycle bin item count',
        'confirm': None,               # read-only
        'timeout_s': 20.0,
        'json': True,
        'args': {},
        'argv': _cmd(
            "$s = New-Object -ComObject Shell.Application; "
            "$b = $s.NameSpace(0xA); "
            "$n = if ($b -and $b.Items()) { @($b.Items()).Count } else { 0 }; "
            "[pscustomobject]@{ items = $n } | ConvertTo-Json -Compress"),
        'describe': 'Number of items currently in the Recycle Bin.',
    },
    'notify_toast': {
        'title': 'show a Windows toast notification',
        'confirm': None,               # display-only
        'timeout_s': 30.0,
        'json': False,
        'args': {
            'text': {'type': 'str', 'min': 1, 'max': 500},
        },
        'argv': _cmd(
            "[Windows.UI.Notifications.ToastNotificationManager, "
            "Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
            "ContentType = WindowsRuntime] | Out-Null; "
            "$t = [System.Security.SecurityElement]::Escape("
            "[string]$env:RAPHAEL_ARG_TEXT); "
            "$x = New-Object Windows.Data.Xml.Dom.XmlDocument; "
            "$x.LoadXml(\"<toast><visual><binding template='ToastText02'>"
            "<text id='1'>Raphael</text><text id='2'>$t</text>"
            "</binding></visual></toast>\"); "
            "$n = [Windows.UI.Notifications.ToastNotificationManager]::"
            "CreateToastNotifier("
            "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\"
            "powershell.exe'); "
            "$n.Show([Windows.UI.Notifications.ToastNotification]::new($x))"),
        'describe': 'Toast notification with title "Raphael" and the given text.',
    },
}

# Registry self-check at import — a malformed script must never ship.
for _sid, _spec in SCRIPTS.items():
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,31}', _sid):
        raise ValueError('bad script_id: %r' % _sid)
    if 'confirm' not in _spec:
        raise ValueError("script %r must declare its confirm category" % _sid)
    if _spec['confirm'] not in (None, 'system_settings_change'):
        raise ValueError("script %r has unknown confirm category %r"
                         % (_sid, _spec['confirm']))
    if not isinstance(_spec.get('argv'), list) or not _spec['argv']:
        raise ValueError('script %r needs a fixed argv list' % _sid)


def _validate_args(script_id: str, args: Any) -> Dict[str, Any]:
    spec = SCRIPTS[script_id]
    declared: Dict[str, Any] = spec.get('args') or {}
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError("field 'args' must be a JSON object")
    extra = sorted(set(args) - set(declared))
    if extra:
        raise ValueError("script '%s' does not declare argument(s): %s"
                         % (script_id, ', '.join(extra)))
    out: Dict[str, Any] = {}
    for name, rule in declared.items():
        if name not in args:
            if rule.get('required'):
                raise ValueError("script '%s' requires argument '%s'"
                                 % (script_id, name))
            continue
        v = args[name]
        if rule.get('type') == 'int':
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError("argument '%s' must be an integer" % name)
            lo, hi = rule.get('min', -2**31), rule.get('max', 2**31 - 1)
            if not (lo <= v <= hi):
                raise ValueError("argument '%s' must be between %d and %d"
                                 % (name, lo, hi))
        else:
            if not isinstance(v, str):
                raise ValueError("argument '%s' must be a string" % name)
            if len(v) > rule.get('max', 500):
                raise ValueError("argument '%s' exceeds %d characters"
                                 % (name, rule.get('max', 500)))
            if len(v) < rule.get('min', 0):
                raise ValueError("argument '%s' is too short" % name)
            pat = rule.get('pattern')
            if pat and not re.fullmatch(pat, v):
                raise ValueError("argument '%s' has an invalid format" % name)
        out[name] = v
    return out


def run_script(script_id: str, args: Dict[str, Any], backend) -> Any:
    """Validate + run a registered script against the backend. Returns the
    parsed JSON value for `json` scripts, else {'output': str}."""
    if script_id not in SCRIPTS:
        raise ActionError('E_UNSUPPORTED',
                          "unknown script_id '%s'" % str(script_id)[:40])
    values = _validate_args(script_id, args)
    spec = SCRIPTS[script_id]
    env = {'RAPHAEL_ARG_%s' % k.upper(): str(v) for k, v in values.items()}
    res = backend.powershell(list(spec['argv']), env,
                             float(spec.get('timeout_s', 20.0)))
    if int(res.get('rc', -1)) != 0:
        raise ActionError('E_INTERNAL', 'script %s failed (rc=%s): %s'
                          % (script_id, res.get('rc'),
                             str(res.get('err') or '')[:200]))
    out = str(res.get('out') or '').strip()
    if not spec.get('json'):
        return {'output': out[:8000]}
    if not out:
        return [] if spec.get('array') else None
    try:
        parsed = json.loads(out)
    except ValueError:
        raise ActionError('E_INTERNAL',
                          'script %s returned non-JSON output' % script_id)
    if spec.get('array') and isinstance(parsed, dict):
        parsed = [parsed]
    return parsed


# ------------------------------------------------------------- act_req -----
def _validate_powershell(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'script_id', 'args'})
    script_id = req_str(args, 'script_id', max_len=32)
    if script_id not in SCRIPTS:
        raise ValueError("unknown script_id '%s'" % script_id[:40])
    raw = args.get('args', {})
    _validate_args(script_id, raw)   # fail before taking the lock
    return {'script_id': script_id, 'args': dict(raw) if isinstance(raw, dict) else {}}


async def _run_powershell(args: Dict[str, Any], backend) -> Any:
    # offload (AUD-16): subprocess must not block the loop AND its worker
    # is tracked for input-lock quarantine on timeout/cancel.
    return await offload(run_script, args['script_id'], args['args'], backend)


register_action('powershell', _run_powershell, validate=_validate_powershell,
                needs_lock=False, confirm='system_settings_change',
                describe='Run a read-only/system query from the fixed script '
                         'registry (script_id + declared args only).')
