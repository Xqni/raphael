"""System control helpers for the Windows Body.

Only a very small subset is required for the initial wave:
- set_volume(level: int) – 0‑100 percent using the Windows Core Audio API.
- set_brightness(level: int) – placeholder that invokes PowerShell
  `Set-DisplayBrightness` if available.
Both functions are best‑effort and log errors instead of raising – the
protocol will report failure via error frames.
"""
import subprocess
import sys
import ctypes
from ctypes import wintypes

try:
    from . import depfail
except ImportError:          # script mode (body/win on sys.path)
    import depfail

# Volume control via the Windows Core Audio API (IAudioEndpointVolume).
# comtypes comes from the PRE-INSTALLED hash-pinned env (SEC-9: no runtime
# pip — missing dep fails loud with a pointer to requirements.txt).
depfail.require('comtypes')
import comtypes.client as cc

def _default_volume():
    devices = cc.CreateObject('{BCDE0395-E52F-467C-8E3D-C4579291692E}',
                              interface=cc.IID_IDeviceEnumerator)
    endpoint = devices.GetDefaultAudioEndpoint(0, 1)  # eRender=0, eConsole=1
    return endpoint.Activate(cc.IID_IAudioEndpointVolume, cc.CLSCTX_ALL, None)


def get_volume():
    """Master playback volume 0-100 (int), or None on failure.
    F-3 inverse ops need the PREVIOUS level — truthfulness over silence."""
    try:
        vol_f = _default_volume().GetMasterVolumeLevelScalar()
        return int(round(vol_f * 100))
    except Exception as e:  # noqa: BLE001
        print(f'[system] Failed to read volume: {e}', file=sys.stderr)
        return None


def set_volume(level: int) -> bool:
    """Set master playback volume (0‑100). Returns True on success — the
    F-3 journal only records undo entries for changes that really happened."""
    if not (0 <= level <= 100):
        raise ValueError('Volume level must be between 0 and 100')
    try:
        volume = _default_volume()
        volume.SetMasterVolumeLevelScalar(level / 100.0, None)
        return True
    except Exception as e:  # noqa: BLE001
        print(f'[system] Failed to set volume: {e}', file=sys.stderr)
        return False


def get_brightness():
    """Current display brightness 0-100, or None (desktop monitors / query
    failure) — F-3 inverse ops need the previous level."""
    ps_cmd = (r'(Get-WmiObject -Namespace root\wmi -Class '
              r'WmiMonitorBrightness | Select-Object -First 1 '
              r'-ExpandProperty CurrentBrightness)')
    try:
        proc = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_cmd],
            capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[:120])
        return int((proc.stdout or '').strip())
    except Exception as e:  # noqa: BLE001
        print(f'[system] Failed to read brightness: {e}', file=sys.stderr)
        return None


def set_brightness(level: int) -> bool:
    """Set display brightness (0‑100) – uses PowerShell if possible.
    Returns True on success (F-3 journal records only real changes)."""
    if not (0 <= level <= 100):
        raise ValueError('Brightness level must be between 0 and 100')
    ps_cmd = rf"(Get-WmiObject -Namespace root\wmi -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})"
    try:
        proc = subprocess.run(['powershell', '-NoProfile', '-NonInteractive',
                               '-Command', ps_cmd],
                              capture_output=True, timeout=15)
        return proc.returncode == 0
    except Exception as e:  # noqa: BLE001
        print(f'[system] Failed to set brightness: {e}', file=sys.stderr)
        return False

if __name__ == '__main__':
    # Simple CLI for manual testing
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--vol', type=int)
    p.add_argument('--bright', type=int)
    args = p.parse_args()
    if args.vol is not None:
        set_volume(args.vol)
        print('Volume set')
    if args.bright is not None:
        set_brightness(args.bright)
        print('Brightness set')
