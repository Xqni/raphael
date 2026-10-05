"""Entry point for raphael-brain.service: resolves the bind host per
PROTOCOL §1 (WSL NAT mode → 0.0.0.0 so Windows' localhost forwarding reaches
the WSL vNIC; mirrored mode → 127.0.0.1), then runs uvicorn on brain.app:app.

Overrides: RAPHAEL_BIND, RAPHAEL_PORT, RAPHAEL_LOG_LEVEL.
"""
import os
import subprocess

import uvicorn


def detect_host() -> str:
    override = os.environ.get('RAPHAEL_BIND')
    if override:
        return override
    try:
        out = subprocess.run(['wslinfo', '--networking-mode'],
                             capture_output=True, text=True, timeout=3)
        if 'mirrored' in (out.stdout or '').lower():
            return '127.0.0.1'
    except Exception:  # noqa: BLE001 — no wslinfo (dev VM) → NAT default
        pass
    return '0.0.0.0'


def main():
    host = detect_host()
    port = int(os.environ.get('RAPHAEL_PORT', '8765'))
    log_level = os.environ.get('RAPHAEL_LOG_LEVEL', 'info')
    uvicorn.run('brain.app:app', host=host, port=port, log_level=log_level)


if __name__ == '__main__':
    main()
