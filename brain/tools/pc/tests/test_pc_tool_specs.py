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
        # Wave 5U: SPEC confirm classes are the gate contract (brain-core
        # P0.2 policy map). The act-layer confirm stays informational legacy
        # metadata (AUD-11) — when present it must be a documented class.
        if action.confirm is not None:
            from brain.tools.pc._spec import CONFIRM_CLASSES
            assert action.confirm in CONFIRM_CLASSES, (name, action.confirm)


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
    # AUD-11 ids are requested from the integrator (safety.* is an authority
    # key — config.d cannot add them); accepted while the request is open.
    pending_req = REPO / 'docs' / 'requests' / \
        'pc-control__to__integrator__config-confirm-categories-aud11.md'
    if pending_req.is_file():
        allowed |= set(re.findall(r'^\s+- ([a-z_]+)\s+# AUD-11',
                                  pending_req.read_text(), re.M))
    from brain.tools.pc._spec import CONFIRM_CLASSES
    for name, spec in pc.SPECS.items():
        meta = registry.describe(name)
        assert meta['risky'] == spec.risky, name
        assert spec.confirm is not None, name   # Wave 5U: every tool tagged
        if spec.risky:
            # risky drives the CURRENT registry gate: a str class must be a
            # config/pending id; a conditional (uia) gates click/type.
            if isinstance(spec.confirm, str):
                assert spec.confirm != 'auto', name
                if spec.confirm != 'gui_input':
                    assert spec.confirm in allowed, (name, spec.confirm)
        else:
            # non-risky: any documented class or conditional tag is fine
            from brain.tools.pc._spec import CONFIRM_CLASSES as _CC
            assert isinstance(spec.confirm, dict) or spec.confirm in _CC, name
    risky = {n for n, s in pc.SPECS.items() if s.risky}
    assert risky == {'powershell', 'open_path', 'uia'}, risky   # AUD-11 set


def test_registry_routes_all_pc_tools_to_body():
    for name in pc.SPECS:
        assert registry.describe(name)['category'] == 'gui', name
        # gui tools must never execute locally
        with pytest.raises(RuntimeError, match='body'):
            registry.get(name)(**{})


def test_risky_pc_tool_set_is_exactly_the_gated_ones():
    # powershell (wave-2) + AUD-11 additions: arbitrary handler-open + GUI
    # submissions. Nothing else may be confirm-gated (or slip past it).
    risky = sorted(n for n, s in pc.SPECS.items() if s.risky)
    assert risky == ['open_path', 'powershell', 'uia'], risky


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
    `test_tool_specs_only_offers_conforming_schemas` against my overwrite —
    including the 3 zero-arg tools now that the empty-properties relaxation
    is merged (allow-empty-properties-schema, ACCEPTED 2026-10-06)."""
    offered = {s['function']['name'] for s in registry.tool_specs()}
    for name, spec in pc.SPECS.items():
        meta = registry.describe(name)
        assert meta['schema'] == spec.schema(), name
        assert name in offered, name
        # No-arg tools must carry the strict empty shape, not be skipped.
        if not spec.properties:
            assert meta['schema'] == {
                'type': 'object', 'properties': {}, 'required': [],
                'additionalProperties': False}, name
    assert offered >= set(pc.SPECS)


def test_descriptions_carry_usage_rules():
    # Cloud models rely on these (they cannot see the body implementation).
    assert 'http' in pc.SPECS['launch_url'].description
    assert 'list_windows' in pc.SPECS['window'].description
    assert 'foreground_info' in pc.SPECS['screenshot'].description
    assert 'input lock' in pc.SPECS['media'].description


# ------------------------------------------------- Wave 5U Wave-A tags ----
def test_confirm_class_tags_match_charter():
    """docs/USEFUL-NOW-PLAN.md §5.2 task 1 — the EXACT tag table. Charter
    list + documented extrapolations (tools the charter predates/silences):
    navigate_url = launch-class auto; notify/report/activity = auto;
    clipboard auto (flagged to brain-core P0.2 in the tags request)."""
    assert set(pc.SPECS) == {
        'activity', 'brightness', 'clipboard', 'foreground_info', 'input',
        'launch_url', 'list_running_apps', 'list_windows', 'media', 'navigate_url',
        'notify', 'open_app', 'open_path', 'powershell', 'report',
        'screenshot', 'search_youtube', 'uia', 'volume', 'window'}, set(pc.SPECS)
    expected_auto = {
        'launch_url', 'navigate_url', 'search_youtube', 'open_app',
        'list_running_apps', 'volume', 'brightness', 'media', 'window',
        'list_windows', 'foreground_info', 'screenshot', 'notify',
        'clipboard', 'report', 'activity',
    }
    for name in expected_auto:
        assert pc.SPECS[name].confirm == 'auto', (name, pc.SPECS[name].confirm)
    assert pc.SPECS['open_path'].confirm == 'open_arbitrary_file'
    assert pc.SPECS['powershell'].confirm == 'system_settings_change'
    assert pc.SPECS['input'].confirm == 'gui_input'
    uia = pc.SPECS['uia'].confirm
    assert uia['default'] == 'auto', uia
    gated = {(w['args']['op']['in'][0], w['class']) for w in uia['when']}
    assert gated == {('click', 'gui_input'), ('type', 'gui_input')}, uia


def test_confirm_tag_validation_is_loud():
    from brain.tools.pc._spec import (CONFIRM_CLASSES, SpecError, ToolSpec,
                                      op_classes)
    base = dict(properties=pc.SPECS['volume'].properties, required=(),
                description='x' * 25)
    bad = [
        {'confirm': 'nope'},                                     # unknown class
        {'confirm': {'default': 'auto'}},                        # missing when
        {'confirm': op_classes('auto', {'not_an_op': 'gui_input'})},  # op not in enum
        {'confirm': None},                                       # missing tag
        {'risky': True, 'confirm': 'auto'},                      # risky+auto
    ]
    for over in bad:
        with pytest.raises(SpecError):
            ToolSpec(name='t_bad', **{**base, **over}).validate()
    # conditional builder output validates (tool must HAVE an op enum)
    with_op = {'description': 'x' * 25, 'required': (), 'properties': {
        'op': {'type': 'string', 'description': 'operation to run.',
               'enum': ['read', 'click', 'type']}}}
    ToolSpec(name='t_ok', confirm=op_classes(
        'auto', {'click': 'gui_input'}), **with_op).validate()
    assert 'gui_input' in CONFIRM_CLASSES
