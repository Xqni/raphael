"""pc tool group: system controls (act_req: volume, brightness, media,
notify, clipboard)."""
from __future__ import annotations

from ._spec import ToolSpec, prop_enum, prop_int, prop_string, spec

_MEDIA_OPS = ['play_pause', 'stop', 'next', 'prev', 'vol_up', 'vol_down',
              'mute']

SPECS = (
    spec(
        'volume',
        'Set the master speaker volume of the Windows PC (0 = silent, '
        '100 = loudest). Read-only action otherwise; no confirmation needed.',
        {'level': prop_int('Volume percent 0-100.', 0, 100)},
        ('level',),
    ),
    spec(
        'brightness',
        'Set the display brightness of the Windows PC (0-100 percent). '
        'Laptops only — desktop monitors may not respond.',
        {'level': prop_int('Brightness percent 0-100.', 0, 100)},
        ('level',),
    ),
    spec(
        'media',
        'Send a media key to control whatever is playing (Spotify, YouTube '
        'in a browser, etc.). play_pause toggles playback; mute toggles '
        'mute. Requires the input lock (it synthesizes keystrokes).',
        {'op': prop_enum('Media command to send.', _MEDIA_OPS)},
        ('op',),
        needs_lock=True,
    ),
    spec(
        'notify',
        'Show a Windows toast notification on the PC with the given text. '
        'Use to surface a short message to the user without speaking.',
        {'text': prop_string('Notification text, 1-500 chars.')},
        ('text',),
    ),
    spec(
        'clipboard',
        'Read the current Windows clipboard text, or overwrite it with new '
        'text. Read returns the raw clipboard string; write replaces the '
        'entire clipboard content. Clipboard text is treated as sensitive: '
        'never echo its value back to the user unless asked.',
        {'op': prop_enum('read = get clipboard text, write = set it.', ['read', 'write']),
         'text': prop_string('Text to write — required only when op=write '
                             '(max 100000 chars).')},
        ('op',),
    ),
)
