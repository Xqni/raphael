"""Registry self-registration + strict spec checks (INTERFACES §(b))."""
import inspect
import json

import pytest

import brain.tools as tool_reg
import brain.tools.computer_use as cu
from brain.tools.computer_use import SPECS

try:                                    # optional: strict schema validator
    import jsonschema
except ImportError:                     # pragma: no cover
    jsonschema = None


def test_tools_registered_with_metadata():
    names = set(tool_reg.names())
    assert {"see_screen", "computer_use"} <= names
    see = tool_reg.describe("see_screen")
    assert see["risky"] is False
    assert see["needs_lock"] is False      # read-only screen peek
    assert see["category"] == "local"
    comp = tool_reg.describe("computer_use")
    assert comp["risky"] is True           # confirm.RISKY_TOOLS includes it
    assert comp["needs_lock"] is True      # drives mouse/keyboard
    assert comp["category"] == "local"


def test_specs_are_strict_json_schema():
    assert set(SPECS) == {"see_screen", "computer_use"}
    for name, spec in SPECS.items():
        assert spec["type"] == "object", name
        assert spec.get("additionalProperties") is False, name
        assert spec.get("required"), name
        props = spec["properties"]
        assert set(spec["required"]) <= set(props), name
        for key, prop in props.items():
            assert "type" in prop, (name, key)
        # round-trip: schema itself must be JSON-serializable
        json.dumps(spec)


def test_tool_signatures_match_specs():
    assert list(inspect.signature(cu.see_screen).parameters) == ["question"]
    assert list(inspect.signature(cu.computer_use).parameters) == ["task"]


@pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")
@pytest.mark.parametrize("name", sorted(SPECS))
def test_specs_validate_with_jsonschema(name):
    schema = {"type": "object", "properties": {"root": SPECS[name]},
              "required": ["root"]}
    jsonschema.validate({"root": {"question": "what is this?"}}
                        if name == "see_screen"
                        else {"root": {"task": "open notepad"}}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"root": {"question": "x", "extra": 1}} if name == "see_screen"
            else {"root": {"task": "x", "extra": 1}}, schema)


def test_registry_dispatches_to_registered_callables():
    assert tool_reg.get("see_screen") is cu.see_screen
    assert tool_reg.get("computer_use") is cu.computer_use
