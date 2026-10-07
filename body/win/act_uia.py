"""`uia` action — structured UI Automation ops (PROTOCOL §7
`uia{op, element, args}`).

Ops:
* find  -> locate an element (descriptor or found:false)
* click -> click it (input injection -> needs_lock, handled by the action)
* type  -> focus it and type text (clear_first defaults to True)
* read  -> element descriptor + its text content
* tree  -> element descriptor + its child tree (depth-capped)

`element` is a structured selector (name/control_type/automation_id/
class_name/index) — never free-form coordinates-as-text, never a shell
string. Element trees and read text are UNTRUSTED screen content on the
Brain side (AGENT_RULES §9).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

try:
    from .actions import opt_bool, reject_extra, register_action
except ImportError:  # script mode
    from actions import opt_bool, reject_extra, register_action

_OPS = {'find', 'click', 'type', 'read', 'tree'}
_SELECTOR_KEYS = {'name', 'control_type', 'automation_id', 'class_name', 'index'}
# UIA ControlType names (case-insensitive match in the backend).
_CONTROL_TYPES = {
    'button', 'calendar', 'checkbox', 'combobox', 'custom', 'dataitem',
    'document', 'edit', 'group', 'hyperlink', 'image', 'list', 'listitem',
    'menu', 'menubar', 'pane', 'progressbar', 'radiobutton', 'scrollbar',
    'semantic', 'separator', 'slider', 'spinner', 'splitbutton', 'statusbar',
    'tab', 'tabitem', 'table', 'text', 'thumb', 'titlebar', 'tool', 'tooltip',
    'tree', 'treeitem', 'window',
}
_MAX_TYPE = 2000


def _validate_element(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("field 'element' must be a JSON object")
    reject_extra(raw, _SELECTOR_KEYS, where="field 'element'")
    criteria = [k for k in ('name', 'control_type', 'automation_id', 'class_name')
                if k in raw]
    if not criteria:
        raise ValueError("field 'element' needs at least one of: name, "
                         "control_type, automation_id, class_name")
    out: Dict[str, Any] = {}
    for key in ('name', 'automation_id', 'class_name'):
        if key in raw:
            v = raw[key]
            if not isinstance(v, str) or not v or len(v) > 200:
                raise ValueError("field 'element.%s' must be a 1..200 char string" % key)
            out[key] = v
    if 'control_type' in raw:
        ct = raw['control_type']
        if not isinstance(ct, str) or ct.lower() not in _CONTROL_TYPES:
            raise ValueError("field 'element.control_type' is not a UIA "
                             "ControlType name")
        out['control_type'] = ct
    if 'index' in raw:
        idx = raw['index']
        if isinstance(idx, bool) or not isinstance(idx, int) or not (0 <= idx <= 99):
            raise ValueError("field 'element.index' must be 0..99")
        out['index'] = idx
    return out


def _validate_uia(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'op', 'element', 'args'})
    op = args.get('op')
    if not isinstance(op, str) or op not in _OPS:
        raise ValueError("field 'op' must be one of: %s"
                         % ', '.join(sorted(_OPS)))
    if 'element' not in args:
        raise ValueError("missing required field 'element'")
    out: Dict[str, Any] = {'op': op,
                           'element': _validate_element(args['element'])}
    raw_args = args.get('args') or {}
    if not isinstance(raw_args, dict):
        raise ValueError("field 'args' must be a JSON object")
    args = dict(raw_args)
    timeout_s = args.get('timeout_s', 5)
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) \
            or not (0.5 <= float(timeout_s) <= 15):
        raise ValueError("field 'args.timeout_s' must be a number 0.5..15")
    out['timeout_s'] = float(timeout_s)

    if op == 'type':
        reject_extra(args, {'timeout_s', 'text', 'clear'}, where="field 'args'")
        if 'text' not in args:
            raise ValueError("op 'type' requires args.text")
        text = args['text']
        if not isinstance(text, str) or not text or len(text) > _MAX_TYPE:
            raise ValueError("field 'args.text' must be a 1..%d char string" % _MAX_TYPE)
        if any(ord(ch) < 32 for ch in text):
            raise ValueError("field 'args.text' must not contain control characters")
        out['text'] = text
        out['clear'] = opt_bool(args, 'clear', default=True)
    elif op == 'click':
        reject_extra(args, {'timeout_s', 'button'}, where="field 'args'")
        out['button'] = args.get('button', 'left')
        if out['button'] not in ('left', 'right'):
            raise ValueError("field 'args.button' must be left or right")
    elif op == 'tree':
        reject_extra(args, {'timeout_s', 'depth'}, where="field 'args'")
        depth = args.get('depth', 1)
        if isinstance(depth, bool) or not isinstance(depth, int) or not (1 <= depth <= 3):
            raise ValueError("field 'args.depth' must be 1..3")
        out['depth'] = depth
    else:  # find / read
        reject_extra(args, {'timeout_s'}, where="field 'args'")
    return out


async def _run_uia(args: Dict[str, Any], backend) -> Any:
    op, sel = args['op'], args['element']
    timeout_s = args['timeout_s']
    if op == 'find':
        found = await asyncio.to_thread(backend.uia_find, sel, timeout_s)
        return found if found is not None else {'found': False}
    if op == 'click':
        return await asyncio.to_thread(backend.uia_click, sel, timeout_s,
                                       args['button'])
    if op == 'type':
        return await asyncio.to_thread(backend.uia_type, sel, args['text'],
                                       args['clear'], timeout_s)
    if op == 'read':
        return await asyncio.to_thread(backend.uia_read, sel, timeout_s)
    # tree
    return await asyncio.to_thread(backend.uia_tree, sel, args['depth'],
                                   timeout_s)


register_action('uia', _run_uia, validate=_validate_uia,
                needs_lock=True, confirm=None,
                describe='UI Automation: find/click/type/read/tree over a '
                         'structured element selector.')
