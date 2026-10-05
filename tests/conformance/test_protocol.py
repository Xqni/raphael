import pytest
import re
from pathlib import Path

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
