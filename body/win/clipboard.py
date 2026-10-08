"""Clipboard helper for the Windows Body.

Simple get/set using the `win32clipboard` module (pywin32). Dependencies
come from the PRE-INSTALLED hash-pinned environment only
(body/win/requirements.txt); missing dep fails loud (SEC-9, no runtime pip).
"""
import sys

try:
    from . import depfail
except ImportError:          # script mode (body/win on sys.path)
    import depfail

depfail.require('pywin32', 'win32api')
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
