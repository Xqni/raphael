"""Application launching utilities for the Windows Body.

Provides simple wrappers for opening URLs, file paths, or executables.
All calls are performed via the standard Windows `start` command to avoid
shell injection – the path/URL is passed as a separate argument.
"""
import subprocess
import sys
import os

def open_url(url: str):
    """Open a URL in the default browser using `start` (Windows)."""
    # Using `cmd /c start` ensures the command runs detached.
    subprocess.Popen(['cmd', '/c', 'start', '', url], shell=False)

def open_path(path: str):
    """Open a file or folder in Explorer."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    subprocess.Popen(['explorer', path], shell=False)

def launch_executable(exe_path: str, *args: str):
    """Launch an executable with optional arguments."""
    if not os.path.isfile(exe_path):
        raise FileNotFoundError(exe_path)
    subprocess.Popen([exe_path, *args], shell=False)

if __name__ == '__main__':
    # Minimal manual test – pass a URL or path as argument.
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg.startswith('http'):
            open_url(arg)
        else:
            open_path(arg)
    else:
        print('Usage: apps.py <url|path>')
