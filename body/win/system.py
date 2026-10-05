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

# Volume control via the Windows Core Audio API (IAudioEndpointVolume).
# We lazily import comtypes – install if missing.
def _ensure_pkg(name: str):
    try:
        __import__(name)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', name])
        __import__(name)

_ensure_pkg('comtypes')
import comtypes.client as cc

def set_volume(level: int):
    """Set master playback volume (0‑100)."""
    if not (0 <= level <= 100):
        raise ValueError('Volume level must be between 0 and 100')
    try:
        devices = cc.CreateObject('{BCDE0395-E52F-467C-8E3D-C4579291692E}', interface=cc.IID_IDeviceEnumerator)
        # Enumerate default audio endpoint (render, console)
        endpoint = devices.GetDefaultAudioEndpoint(0, 1)  # eRender=0, eConsole=1
        volume = endpoint.Activate(cc.IID_IAudioEndpointVolume, cc.CLSCTX_ALL, None)
        # Convert 0‑100 to 0.0‑1.0
        vol_f = level / 100.0
        volume.SetMasterVolumeLevelScalar(vol_f, None)
    except Exception as e:
        print(f'[system] Failed to set volume: {e}', file=sys.stderr)

def set_brightness(level: int):
    """Set display brightness (0‑100) – uses PowerShell if possible.
    Windows 10+ supports `Set-DisplayBrightness` via WmiMonitorBrightnessMethods.
    """
    if not (0 <= level <= 100):
        raise ValueError('Brightness level must be between 0 and 100')
    ps_cmd = f"(Get-WmiObject -Namespace root\wmi -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})"
    try:
        subprocess.run(['powershell', '-Command', ps_cmd], check=True, capture_output=True)
    except Exception as e:
        print(f'[system] Failed to set brightness: {e}', file=sys.stderr)

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
