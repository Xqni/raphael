"""ToolSpec — strict OpenAI-style function specs for the pc tools.

Contract (INTERFACES §b): strict JSON Schema (`type: "object"` params, every
property typed + described, `required` listed, `additionalProperties: false`),
plus the two enforcement metadata fields:

* `needs_lock` — input-lock arbitration (mirrors the body action exactly);
* `confirm`    — the confirm category that applies (None = no confirmation;
                 values must come from config `safety.confirm_actions`).

Only provider-portable keywords are allowed (`type`, `description`, `enum`,
`minimum`, `maximum`, `items`) so Groq/OpenAI-compatible endpoints accept the
schemas as-is. Constraints that JSON Schema could express but providers often
reject (patterns, min-length) live in the description instead — the BODY
re-validates every argument regardless (body/win/actions.py), so the schema
is guidance, never the security boundary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

_NAME_RE = re.compile(r'[a-z][a-z0-9_]{2,47}\Z')
_TYPE_OK = {'string', 'integer', 'number', 'boolean', 'object', 'array'}
_KEYWORDS_OK = {'type', 'description', 'enum', 'minimum', 'maximum', 'items'}
_OBJECT_KEYWORDS = {'properties', 'additionalProperties', 'required'}

# Wave 5U Wave-A confirm classes (docs/USEFUL-NOW-PLAN.md §5.2 task 1 +
# P0.2; proposed to brain-core in
# docs/requests/pc-control__to__brain-core__confirm-class-tags.md — they own
# the policy map, this is the per-tool tag vocabulary):
#   auto                — never confirms (read-only / reversible / launch)
#   open_arbitrary_file — handler-opens an arbitrary exe/document (exists)
#   system_settings_change — fixed-registry script run (exists)
#   gui_input           — NEW: keystrokes/form input. Confirms ONLY when the
#                         focused element is a password field or a submit
#                         control on a non-allowlisted site -> escalates to
#                         gui_submission (evaluation lands with brain-core's
#                         policy map; body already exposes
#                         foreground_info.focused_is_password).
#   gui_submission      — high-impact GUI submission (escalation target)
CONFIRM_CLASSES = frozenset({
    'auto', 'open_arbitrary_file', 'system_settings_change',
    'gui_input', 'gui_submission',
})


def op_classes(default: str, when: Dict[str, str]) -> Dict[str, Any]:
    """Conditional per-op confirm tag (uia: read/find/tree auto, click/type
    gui_input). `when` maps an op name -> class; only declared ops differ
    from the default."""
    return {'default': default,
            'when': [{'args': {'op': {'in': [op]}}, 'class': cls}
                     for op, cls in sorted(when.items())]}


def _validate_confirm_tag(name: str, confirm: Any, properties: Dict) -> None:
    """confirm must be a class string or {default, when[...]} conditional."""
    def _class(c: Any, where: str) -> None:
        if c not in CONFIRM_CLASSES:
            raise SpecError('%r: %s is not a confirm class (have: %s)'
                            % (name, c, ', '.join(sorted(CONFIRM_CLASSES))))

    if isinstance(confirm, str):
        _class(confirm, 'confirm')
        return
    if isinstance(confirm, dict):
        if set(confirm) != {'default', 'when'} or not isinstance(
                confirm['when'], list) or not confirm['when']:
            raise SpecError('%r: conditional confirm must be '
                            '{default, when:[{args:{...}, class}]}' % name)
        _class(confirm['default'], 'confirm.default')
        for entry in confirm['when']:
            if not isinstance(entry, dict) or set(entry) != {'args', 'class'}:
                raise SpecError('%r: when entries must be {args, class}'
                                % name)
            _class(entry['class'], 'when.class')
            args = entry['args']
            if not isinstance(args, dict) or set(args) != {'op'}:
                raise SpecError('%r: only op-based conditions are supported '
                                '(Wave A)' % name)
            for op, rule in args['op'].items():
                if op != 'in' or not isinstance(rule, list) or not rule:
                    raise SpecError('%r: op condition must be {"in": [...]}' % name)
                known = properties.get('op', {}).get('enum')
                if not known:
                    raise SpecError('%r: op-based conditions but the tool '
                                    'has no op enum property' % name)
                for opname in rule:
                    if opname not in known:
                        raise SpecError('%r: conditional op %r is not in the '
                                        "tool's op enum" % (name, opname))
        return
    raise SpecError('%r: confirm must be a class string or conditional dict'
                    % name)


class SpecError(ValueError):
    """A tool spec is malformed — raised LOUDLY at import (INTERFACES §b)."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    properties: Dict[str, Dict[str, Any]]
    required: Tuple[str, ...]
    needs_lock: bool = False
    risky: bool = False
    confirm: Any = None              # confirm class str | {default, when}
    group: str = 'pc'

    # -- shapes ----------------------------------------------------------
    def schema(self) -> Dict[str, Any]:
        return {
            'type': 'object',
            'properties': dict(self.properties),
            'required': list(self.required),
            'additionalProperties': False,
        }

    def openai(self) -> Dict[str, Any]:
        return {'type': 'function',
                'function': {'name': self.name,
                             'description': self.description,
                             'parameters': self.schema()}}

    # -- self-check (runs at import; a bad spec never ships) -------------
    def validate(self) -> None:
        if not _NAME_RE.match(self.name):
            raise SpecError('%r: tool name must be snake_case [a-z0-9_]' % self.name)
        if len(self.description) < 20:
            raise SpecError('%r: description too short (%d chars) — cloud '
                            'models need the usage rules' % (self.name,
                                                            len(self.description)))
        if not isinstance(self.properties, dict):
            raise SpecError('%r: properties must be an object' % self.name)
        _validate_props(self.properties, self.name)
        if not isinstance(self.required, tuple):
            raise SpecError('%r: required must be a tuple' % self.name)
        missing = [r for r in self.required if r not in self.properties]
        if missing:
            raise SpecError('%r: required lists unknown property(s): %s'
                            % (self.name, ', '.join(missing)))
        if self.confirm is None:
            # Wave 5U Wave A: every pc tool carries an explicit confirm
            # class (P0.2 fail-closed default for untagged tools lives on
            # the brain-core side — tagged here so the map can never guess).
            raise SpecError('%r: missing confirm class (CONFIRM_CLASSES: %s)'
                            % (self.name, ', '.join(sorted(CONFIRM_CLASSES))))
        _validate_confirm_tag(self.name, self.confirm, self.properties)
        if self.risky:
            gated = (self.confirm if isinstance(self.confirm, str)
                     else 'conditional')
            if gated == 'auto':
                # risky=True drives the current registry confirm gate — a
                # risky tool tagged auto would silently bypass it.
                raise SpecError('%r: risky=True cannot carry class auto'
                                % self.name)


def _validate_props(properties: Dict[str, Any], path: str) -> None:
    """Recursive property check: every property typed + described, only
    provider-portable keywords, nested object schemas validated too."""
    for key, prop in properties.items():
        where = '%s.%s' % (path, key)
        if not isinstance(key, str) or not key:
            raise SpecError('%s: bad property name %r' % (path, key))
        if not isinstance(prop, dict):
            raise SpecError('%s: property must be an object' % where)
        allowed = set(_KEYWORDS_OK)
        if prop.get('type') == 'object':
            allowed |= _OBJECT_KEYWORDS
        unknown = set(prop) - allowed
        if unknown:
            raise SpecError('%s: unsupported schema keyword(s): %s'
                            % (where, ', '.join(sorted(unknown))))
        if prop.get('type') not in _TYPE_OK:
            raise SpecError('%s: missing/invalid type %r'
                            % (where, prop.get('type')))
        desc = prop.get('description')
        if not isinstance(desc, str) or len(desc) < 5:
            raise SpecError('%s: every property needs a description' % where)
        if 'enum' in prop and (not isinstance(prop['enum'], list)
                                or not prop['enum']):
            raise SpecError('%s: enum must be a non-empty list' % where)
        if prop['type'] == 'object':
            if 'additionalProperties' in prop and \
                    prop['additionalProperties'] is not False:
                raise SpecError('%s: nested objects must set '
                                'additionalProperties: false' % where)
            nested = prop.get('properties')
            if nested is None:
                raise SpecError('%s: object properties need a "properties" '
                                'map (strict schema)' % where)
            if not isinstance(nested, dict):
                raise SpecError('%s: properties must be a map' % where)
            _validate_props(nested, where)
            req = prop.get('required', [])
            if not isinstance(req, list) or \
                    any(r not in nested for r in req):
                raise SpecError('%s: required must list declared properties'
                                % where)
        if prop['type'] == 'array':
            if 'items' not in prop:
                raise SpecError('%s: array needs items schema' % where)
            items = prop['items']
            if not isinstance(items, dict):
                raise SpecError('%s: items must be a schema object' % where)
            _validate_props({'item': items}, where)


# -- tiny builders keeping the group files readable -------------------------
def prop_string(description: str) -> Dict[str, Any]:
    return {'type': 'string', 'description': description}


def prop_int(description: str, lo: int, hi: int) -> Dict[str, Any]:
    return {'type': 'integer', 'description': description,
            'minimum': lo, 'maximum': hi}


def prop_enum(description: str, values: List[str]) -> Dict[str, Any]:
    return {'type': 'string', 'description': description, 'enum': values}


def prop_bool(description: str) -> Dict[str, Any]:
    return {'type': 'boolean', 'description': description}


def spec(name: str, description: str, properties: Dict[str, Dict[str, Any]],
         required: Tuple[str, ...], *, needs_lock: bool = False,
         risky: bool = False, confirm: Any = None) -> ToolSpec:
    return ToolSpec(name=name, description=description, properties=properties,
                    required=required, needs_lock=needs_lock, risky=risky,
                    confirm=confirm)
