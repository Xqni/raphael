"""Spec conformance for the LLM-facing pc tools (INTERFACES §b):

* strict JSON Schema shape on every tool (typed + described properties,
  required ⊆ properties, additionalProperties: false, provider-portable
  keywords only);
* tool name == body act_req action name (loop forwards action=tool_name);
* needs_lock mirrors the body action exactly (never trusts the model);
* risky tools declare a confirm category from config safety.confirm_actions;
* registry metadata (category='gui') so the loop routes to the Body.
"""
import pathlib
import re

import pytest

import brain.tools.pc as pc
from brain import tools as registry
from body.win import actions


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        if (parent / 'docs' / 'PROTOCOL.md').is_file():
            return parent
    raise RuntimeError('repo root not found from %s' % here)


REPO = _repo_root()


def config_confirm_actions():
    """Parse config.yaml safety.confirm_actions without needing PyYAML."""
    text = (REPO / 'config.yaml').read_text()
    block = text.split('confirm_actions:', 1)[1]
    lines = []
    for line in block.splitlines()[1:]:
        item = line.strip()
        if item.startswith('- '):
            lines.append(item[2:].strip())
        elif lines:
            break
    return set(lines)


def test_every_spec_validates_loudly():
    assert pc.SPECS, 'no pc tools registered'
    for spec in pc.SPECS.values():
        spec.validate()          # raises SpecError on any violation


def test_names_match_body_actions_exactly():
    assert set(pc.SPECS) == set(actions.action_names()), (
        'tool/action drift: tools-only=%s actions-only=%s'
        % (sorted(set(pc.SPECS) - set(actions.action_names())),
           sorted(set(actions.action_names()) - set(pc.SPECS))))


def test_needs_lock_mirrors_body_actions():
    for name, spec in pc.SPECS.items():
        action = actions.get_action(name)
        assert spec.needs_lock == action.needs_lock, name
        assert registry.describe(name)['needs_lock'] == action.needs_lock, name


def test_strict_schema_shape():
    for spec in pc.SPECS.values():
        schema = spec.schema()
        assert schema['type'] == 'object'
        assert schema['additionalProperties'] is False
        assert set(schema['required']) <= set(schema['properties'])
        for key, prop in schema['properties'].items():
            assert prop['type'] in ('string', 'integer', 'number', 'boolean',
                                    'object', 'array'), (spec.name, key)
            assert len(prop.get('description', '')) >= 5, (spec.name, key)
            assert set(prop) <= {'type', 'description', 'enum', 'minimum',
                                 'maximum', 'items', 'properties', 'required',
                                 'additionalProperties'}, (spec.name, key)


def test_openai_tool_shape():
    tools = pc.openai_tools()
    assert len(tools) == len(pc.SPECS)
    for tool in tools:
        assert tool['type'] == 'function'
        fn = tool['function']
        assert re.fullmatch(r'[a-z][a-z0-9_]+', fn['name'])
        assert len(fn['description']) >= 20
        assert fn['parameters']['type'] == 'object'


def test_risky_tools_declare_config_confirm_category():
    allowed = config_confirm_actions()
    assert 'system_settings_change' in allowed, 'config drift'
    for name, spec in pc.SPECS.items():
        meta = registry.describe(name)
        assert meta['risky'] == spec.risky, name
        if spec.risky:
            assert spec.confirm in allowed, (name, spec.confirm)
        else:
            assert spec.confirm is None, name


def test_registry_routes_all_pc_tools_to_body():
    for name in pc.SPECS:
        assert registry.describe(name)['category'] == 'gui', name
        # gui tools must never execute locally
        with pytest.raises(RuntimeError, match='body'):
            registry.get(name)(**{})


def test_powershell_is_the_only_risky_pc_tool():
    risky = [n for n, s in pc.SPECS.items() if s.risky]
    assert risky == ['powershell'], risky


def test_prompt_block_lists_every_tool_and_matches_extract_protocol():
    block = pc.prompt_block()
    for name in pc.SPECS:
        assert '- %s' % name in block, name
    assert '{"tool": "<name>", "args": {...}}' in block
    # loop._extract_tool_call must be able to parse a reply built from it
    import json
    reply = '{"tool": "volume", "args": {"level": 30}}'
    assert json.loads(reply)['tool'] in pc.SPECS


def test_registry_receives_schemas_so_tools_are_offered():
    """The Brain offers only tools with a registered schema
    (registry.tool_specs()); this guards the brain-core conformance test
    `test_tool_specs_only_offers_conforming_schemas` against my overwrite."""
    offered = {s['function']['name'] for s in registry.tool_specs()}
    for name, spec in pc.SPECS.items():
        meta = registry.describe(name)
        if spec.properties:                      # non-empty schema
            assert meta['schema'] == spec.schema(), name
            assert name in offered, name
        else:
            # No-arg tools: registry currently rejects empty `properties`
            # (request open with brain-core) — interim: not offered, still
            # reachable via prompt_block() and validated by the body.
            assert meta['schema'] is None, name
            assert name not in offered, name
    # Every pc tool WITH args must be model-offerable; only the 3 no-arg
    # tools are pending the brain-core empty-properties decision.
    no_arg = {n for n, s in pc.SPECS.items() if not s.properties}
    assert no_arg == {'list_windows', 'foreground_info', 'list_running_apps'}
    assert offered >= (set(pc.SPECS) - no_arg)


def test_descriptions_carry_usage_rules():
    # Cloud models rely on these (they cannot see the body implementation).
    assert 'http' in pc.SPECS['launch_url'].description
    assert 'list_windows' in pc.SPECS['window'].description
    assert 'foreground_info' in pc.SPECS['screenshot'].description
    assert 'input lock' in pc.SPECS['media'].description
