"""Clipboard helper for the Windows Body.

Simple get/set using the `win32clipboard` module (pywin32). The functions are
tiny wrappers; if pywin32 is unavailable they are installed automatically.
"""
import sys
import subprocess

def _ensure_pkg(name: str):
    try:
        __import__(name)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', name])
        __import__(name)

_ensure_pkg('pywin32')
import win32clipboard as wc

def set_clipboard_text(text: str):
    wc.OpenClipboard()
    wc.EmptyClipboard()
    wc.SetClipboardText(text, wc.CF_UNICODETEXT)
    wc.CloseClipboard()

def get_clipboard_text() -> str:
    wc.OpenClipboard()
    try:
        data = wc.GetClipboardData(wc.CF_UNICODETEXT)
    finally:
        wc.CloseClipboard()
    return data

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--set', dest='set_text')
    p.add_argument('--get', action='store_true')
    args = p.parse_args()
    if args.set_text:
        set_clipboard_text(args.set_text)
        print('Clipboard set.')
    if args.get:
        print('Clipboard contains:', get_clipboard_text())
