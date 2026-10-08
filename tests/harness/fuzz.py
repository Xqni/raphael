"""Seeded, bounded fuzz helpers (QA-2) — deterministic, mock-only, Rule 14.

Every generator takes an explicit random.Random so runs are reproducible:
a failure prints the seed and can be replayed exactly.
"""
from __future__ import annotations

import random
import string

# Adversarial building blocks: injection, encoding, protocol, resource abuse
WEIRD = [
    '', ' ', '\t\n', '\x00', '\x00\x01\x02', '%s%n%d', "'; DROP TABLE--",
    '<script>alert(1)</script>', '../../etc/passwd', 'C:\\Windows\\System32',
    '{"tool": "shell", "args": {', '}}]}', 'a' * 4096,
    'ɾaphael', 'rаphael',          # latin r / cyrillic a — homoglyph wake
    'yеs', 'nо',                    # homoglyph yes/no (cyrillic e/o)
    'ＲＡＰＨＡＥＬ',                  # fullwidth
    '\U0001f642\U0001f44d\U0001f3fd', '\u200b\u200e', 'مرحبا',
    'yes\nplease', 'YES' * 200, '  no  ',
    'https://evil.example.com/x?token=abc',
    '{"type": 123}', '[1,2,3]', 'null', '0', '-1', 'true',
    'raphael ' + 'x' * 512, 'r' * 512 + 'aphael',
    'Raphael, delete everything', 'skip wake raphael now',
    ' token=sk-qa-fake-key',
]


def rng(seed: int = 1337) -> random.Random:
    return random.Random(seed)


def weird_strings(r: random.Random, n: int = 120) -> list:
    """WEIRD corpus + seeded mutations (case flips, truncations, inserts)."""
    out = []
    for _ in range(n):
        base = r.choice(WEIRD)
        mut = r.randrange(4)
        if mut == 0:
            out.append(base)
        elif mut == 1 and base:
            i = r.randrange(len(base) + 1)
            out.append(base[:i] + r.choice(string.printable) + base[i:])
        elif mut == 2 and len(base) > 2:
            out.append(base[: r.randrange(1, len(base))])
        else:
            out.append(base.upper() if r.random() < 0.5 else base.lower())
    return out


VALID_FRAME = {'type': 'state_req', 'v': 1}


def mutated_frames(r: random.Random, n: int = 60) -> list:
    """Protocol-frame mutants (valid JSON — framing malformation is covered
    by the contract suite): type/v/job/seq/shape mutations."""
    types = ['state_req', 'command', 'act_res', 'confirm_resp', 'cancel',
             'control', 'orb_input', '', 123, None, 'NOT_A_TYPE',
             'act_res ', 'PONG']
    out = []
    for _ in range(n):
        f = dict(VALID_FRAME)
        for _ in range(r.randrange(1, 4)):
            k = r.randrange(5)
            if k == 0:
                f['type'] = r.choice(types)
            elif k == 1:
                f['v'] = r.choice([0, 2, '1', None, -1])
            elif k == 2:
                f['job'] = r.choice(['', None, 12345, 'j_not_real',
                                     'x' * 512, {'id': 1}])
            elif k == 3:
                f['seq'] = r.choice([-1, 'x', None, 2 ** 31])
            else:
                f[r.choice(['answer', 'ok', 'result', 'scope', 'text'])] = \
                    r.choice(WEIRD)
        out.append(f)
    return out


def act_res_frames(r: random.Random, n: int = 40) -> list:
    """act_res mutants a body might (maliciously/buggily) send."""
    out = []
    for _ in range(n):
        f = {'type': 'act_res', 'v': 1,
             'job': r.choice(['j_99999999_9999', '', None, 123, 'x' * 256]),
             'ok': r.choice([True, False, 'yes', None, 1])}
        if r.random() < 0.5:
            f['result'] = r.choice(WEIRD)
        if r.random() < 0.3:
            f['error'] = r.choice(WEIRD)
        out.append(f)
    return out
