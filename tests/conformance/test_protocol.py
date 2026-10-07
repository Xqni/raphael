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
    content = Path("docs/PROTOCOL.md").read_text()
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
    content = Path("docs/PROTOCOL.md").read_text()
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
    
    content = protocol_path.read_text()
    # Find line with `control` action enum
    # Line 43: | `control` | cli, ui, body | `action: pause\|resume\|private_on\|private_off\|kill_gui\|watch_on\|watch_off`, `persist: bool` |
    match = re.search(r"action:\s*([^\`]+)", content)
    if not match:
        pytest.fail("Could not find control action enum in PROTOCOL.md")
    
    raw_actions = match.group(1).split(',')[0] # Get only the action part
    # Remove the backslashes used for escaping the pipe in the markdown file
    cleaned_actions = raw_actions.replace('\\', '').strip()
    expected_actions = set(cleaned_actions.split('|'))
    
    hotkeys_content = body_hotkeys_path.read_text()
    found_actions = set(re.findall(r"_post\([\'\"]([^\'\"]+)", hotkeys_content))
    
    for action in found_actions:
        assert action in expected_actions, f"Action '{action}' in hotkeys.py is not defined in PROTOCOL.md"

def test_orb_states_conformance():
    """Verify semantic states in PROTOCOL.md."""
    content = Path("docs/PROTOCOL.md").read_text()
    match = re.search(r"Semantic states \(server-authoritative\):\s*([^.]+)", content)
    if not match:
        pytest.fail("Could not find semantic states in PROTOCOL.md")
    
    states_str = match.group(1)
    expected_states = {s.strip() for s in states_str.split('|')}
    
    required = {"idle", "thinking", "speaking", "reconnecting", "offline"}
    assert required.issubset(expected_states), f"Missing core states: {required - expected_states}"
