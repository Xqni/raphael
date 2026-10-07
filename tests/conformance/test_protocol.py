import pytest
import re
from pathlib import Path

# ---- Brain → Client frame whitelist (PROTOCOL §3) -------------------------
# Integrator-approved additive frames (e.g. `notice`, 2026-10-07) must be
# added HERE deliberately when they land in §3 — this is the whitelist that
# lets brain-core's emitters pass conformance without re-parsing prose.
BRAIN_TO_CLIENT_FRAMES = {
    'auth_ok', 'auth_fail',      # §2 handshake result
    'ack',                       # request accepted
    'job_event',                 # job lifecycle/progress
    'notice',                    # additive 2026-10-07 (no state change)
    'answer',                    # final reply (additive 2026-10-07, integrator hand-edit with §3 row)
    'report',                    # long-form/Analysis artifact (additive 2026-10-07, same hand-edit)
    'act_req',                   # Body action (§7)
    'speak',                     # TTS stream (JSON side)
    'stt_final',                 # final transcript
    'orb_state',                 # orb display state (§8)
    'subtitle',                  # fading status line
    'needs_confirm',             # confirmation request (§9)
    'error',                     # §10 error frame
    'pong',                      # heartbeat reply
}


def _protocol_brain_to_client_types() -> set:
    """Parse the `**Brain → Client:**` table in PROTOCOL §3 → frame types."""
    content = Path("docs/PROTOCOL.md").read_text(encoding="utf-8")
    marker = "**Brain → Client:**"
    start = content.find(marker)
    assert start != -1, "PROTOCOL §3 Brain → Client section not found"
    types = set()
    for line in content[start:].splitlines():
        if line.startswith("## ") or (line.startswith("**") and line != marker):
            break
        if not line.startswith("|"):
            continue
        first_cell = line.strip("|").split("|")[0]
        found = re.findall(r"`([a-z_]+)`", first_cell)
        if found:
            types.update(found)
    return types


def test_brain_to_client_frame_whitelist_matches_protocol():
    """Every §3 Brain → Client frame is whitelisted, and no stale whitelist
    entry is undocumented — additive frames (e.g. `notice`) must be added to
    BRAIN_TO_CLIENT_FRAMES in the same change that lands them in PROTOCOL."""
    documented = _protocol_brain_to_client_types()
    assert documented == BRAIN_TO_CLIENT_FRAMES, (
        f"undocumented whitelist entries: "
        f"{sorted(BRAIN_TO_CLIENT_FRAMES - documented)} | "
        f"unwhitelisted §3 frames: {sorted(documented - BRAIN_TO_CLIENT_FRAMES)}")


def test_notice_frame_shape():
    """The additive `notice` row (2026-10-07): ui,cli + text/level/ts/job? —
    additive only, orb_state stays the sole state authority."""
    content = Path("docs/PROTOCOL.md").read_text(encoding="utf-8")
    row = next((l for l in content.splitlines()
                if l.startswith("| `notice`")), None)
    assert row is not None, "notice row missing from PROTOCOL §3"
    assert "| ui, cli |" in row, row
    for field in ("text", "level", "ts", "job"):
        assert f"`{field}" in row, (field, row)   # escaped pipes: no split

def test_protocol_enums_match_body():
    """Guard against drift between PROTOCOL.md and body/win code."""
    protocol_path = Path("docs/PROTOCOL.md")
    body_hotkeys_path = Path("body/win/hotkeys.py")
    
    if not protocol_path.exists():
        pytest.fail("PROTOCOL.md not found")
    
    content = protocol_path.read_text(encoding="utf-8")
    # Find line with `control` action enum
    # Line 43: | `control` | cli, ui, body | `action: pause\|resume\|private_on\|private_off\|kill_gui\|watch_on\|watch_off`, `persist: bool` |
    match = re.search(r"action:\s*([^\`]+)", content)
    if not match:
        pytest.fail("Could not find control action enum in PROTOCOL.md")
    
    raw_actions = match.group(1).split(',')[0] # Get only the action part
    # Remove the backslashes used for escaping the pipe in the markdown file
    cleaned_actions = raw_actions.replace('\\', '').strip()
    expected_actions = set(cleaned_actions.split('|'))
    
    hotkeys_content = body_hotkeys_path.read_text(encoding="utf-8")
    found_actions = set(re.findall(r"_post\([\'\"]([^\'\"]+)", hotkeys_content))
    
    for action in found_actions:
        assert action in expected_actions, f"Action '{action}' in hotkeys.py is not defined in PROTOCOL.md"

def test_orb_states_conformance():
    """Verify semantic states in PROTOCOL.md."""
    content = Path("docs/PROTOCOL.md").read_text(encoding="utf-8")
    match = re.search(r"Semantic states \(server-authoritative\):\s*([^.]+)", content)
    if not match:
        pytest.fail("Could not find semantic states in PROTOCOL.md")
    
    states_str = match.group(1)
    expected_states = {s.strip() for s in states_str.split('|')}
    
    required = {"idle", "thinking", "speaking", "reconnecting", "offline"}
    assert required.issubset(expected_states), f"Missing core states: {required - expected_states}"


# ---- Wave-5 format contract: emitters must match §3 ------------------------
def _protocol_client_to_brain_types() -> set:
    """Parse the CLIENT → Brain half of PROTOCOL §3 (before the marker)."""
    content = Path("docs/PROTOCOL.md").read_text(encoding="utf-8")
    start = content.find("## 3. Message envelope")
    marker = "**Brain → Client:**"
    assert start != -1 and content.find(marker) > start
    types = set()
    for line in content[start:content.find(marker)].splitlines():
        if not line.startswith("|"):
            continue
        first_cell = line.strip("|").split("|")[0]
        types.update(re.findall(r"`([a-z_]+)`", first_cell))
    return types


_PROD_FRAME = re.compile(
    r"\{[^{}]*?'type':\s*'([a-z_]+)'[^{}]*?'v':\s*1[^{}]*\}", re.S)
_PROD_FRAME_ALT = re.compile(
    r"\{[^{}]*?'v':\s*1[^{}]*?'type':\s*'([a-z_]+)'[^{}]*\}", re.S)


def _production_emitted_types() -> dict:
    """Frame types emitted by PRODUCTION code (tests excluded — they
    legitimately probe unknown types like `warp_drive`)."""
    out: dict = {}
    for p in Path("brain").rglob("*.py"):
        if "venv" in p.parts or "__pycache__" in p.parts:
            continue
        if "tests" in p.parts or p.name.startswith("test_"):
            continue
        if p.name in ("manual_ws_client.py", "smoke_test.py", "benchmark.py"):
            continue
        src = p.read_text(encoding="utf-8")
        for m in _PROD_FRAME.findall(src) + _PROD_FRAME_ALT.findall(src):
            out.setdefault(m, set()).add(str(p))
    return out


def test_emitted_frames_are_protocol_documented():
    """Format contract (Wave 5): every frame PRODUCTION emits must be
    documented in PROTOCOL §3 (either half). A new Answer/Notice/Report
    emitter without a §3 row goes red here; a §3 row without a whitelist
    entry is caught by test_brain_to_client_frame_whitelist_matches_protocol."""
    documented = (_protocol_client_to_brain_types()
                  | _protocol_brain_to_client_types()
                  | {'ping'})   # §1 heartbeat; the table documents pong only
    emitted = _production_emitted_types()
    assert emitted, 'frame scan found nothing — pattern broken?'
    undocumented = {t: sorted(src) for t, src in emitted.items()
                    if t not in documented}
    assert not undocumented, (
        f'production emits frames missing from PROTOCOL §3: {undocumented}')
