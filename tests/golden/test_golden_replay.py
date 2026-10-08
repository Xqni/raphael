"""Wave-3 golden job transcripts: replay recorded conversations through a
FRESH isolated instance and diff the normalized frame streams.

Record / re-record (INTENTIONAL contract changes only — review the diff!):
    GOLDEN_RECORD=1 pytest -q tests/golden
"""
import json
import os
from pathlib import Path

import pytest

from golden import replay as gr
from golden.scenarios import SCENARIOS

GOLDEN_DIR = Path(__file__).parent / 'transcripts'


@pytest.mark.parametrize('name', sorted(SCENARIOS))
def test_golden_transcript_replays_identically(client, qa_token, name,
                                               router_to_mock=None):
    # a scripted provider reply for scenarios that reach the router (none of
    # the current three do — fastpath/act only — fixture kept for extension)
    run = SCENARIOS[name]
    snap = gr.snapshot_normalize(run(client, qa_token))
    path = GOLDEN_DIR / f'{name}.jsonl'
    if os.environ.get('GOLDEN_RECORD') == '1':
        GOLDEN_DIR.mkdir(exist_ok=True)
        path.write_text(json.dumps({'scenario': name, 'sessions': snap},
                                   indent=2, ensure_ascii=False) + '\n',
                        encoding='utf-8')
        pytest.skip(f'recorded {path.name}')
    assert path.exists(), f'missing golden {path} — record with GOLDEN_RECORD=1'
    golden = gr.load_golden(path)
    problems = gr.compare(golden, snap)
    assert not problems, ('golden replay mismatch:\n'
                          + '\n'.join(problems))


def test_golden_transcripts_are_credential_and_pii_free():
    """Goldens are COMMITTED — never tokens, sessions, or personal paths."""
    assert GOLDEN_DIR.exists(), 'no golden transcripts recorded yet'
    files = sorted(GOLDEN_DIR.glob('*.jsonl'))
    assert len(files) >= 2, f'expected at least 2 transcripts, got {files}'
    for f in files:
        text = f.read_text(encoding='utf-8')
        assert '<token>' in text, f'{f.name}: auth input should be normalized'
        doc = json.loads(text)
        blob = json.dumps(doc)
        # no raw temp-token value and no j_ date-stamped ids leak
        assert '"token": "' in blob
        import re
        assert not re.search(r'"token": "(?!<token>)', blob), \
            f'{f.name}: raw token stored'
        assert not re.search(r'"job": "j_\\d{8}_', blob), \
            f'{f.name}: unstamped job id leaked'
