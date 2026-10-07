"""Wave 3: schema-normalization edge cases.

Every provider words its payloads slightly differently; the router must hand
callers ONE shape. These tests pin the awkward corners: multi-part content,
flat tool-call objects, legacy `function_call`, dict-vs-string arguments,
missing/odd `usage`, empty `choices`, and junk argument payloads.
"""
from __future__ import annotations

import pytest

from brain.router import RouterError
from brain.router.jsonrepair import repair_arguments
from brain.router.openai_compat import (
    _join_content,
    _parse_chat_response,
    normalize_tool_calls,
)


# --------------------------------------------------------------------------- #
# content normalization
# --------------------------------------------------------------------------- #
def test_join_content_shapes() -> None:
    assert _join_content("plain") == "plain"
    assert _join_content(None) == ""
    assert _join_content([{"type": "text", "text": "a"},
                          {"type": "text", "text": "b"}]) == "ab"
    assert _join_content([{"type": "text", "text": "a"}, "loose"]) == "aloose"
    assert _join_content([{"type": "image_url", "image_url": {}}]) == ""
    assert _join_content(42) == "42"


# --------------------------------------------------------------------------- #
# tool-call normalization across provider dialects
# --------------------------------------------------------------------------- #
def test_flat_tool_call_without_function_wrapper() -> None:
    out = normalize_tool_calls([{"name": "shell", "arguments": '{"cmd":"ls"}'}])
    assert out[0]["function"] == {"name": "shell", "arguments": {"cmd": "ls"}}
    assert out[0]["type"] == "function"
    assert out[0]["repaired"] is False


def test_legacy_single_function_call_becomes_a_list() -> None:
    out = normalize_tool_calls(
        {"name": "open_app", "arguments": '{"name": "notepad"}'})
    assert isinstance(out, list) and len(out) == 1
    assert out[0]["function"]["name"] == "open_app"


def test_arguments_may_already_be_a_dict() -> None:
    out = normalize_tool_calls([{"function": {"name": "x",
                                              "arguments": {"a": 1}}}])
    assert out[0]["function"]["arguments"] == {"a": 1}
    assert out[0]["arguments_raw"] is None
    assert out[0]["repaired"] is False


def test_args_alias_and_missing_arguments() -> None:
    out = normalize_tool_calls([{"name": "x", "args": {"k": "v"}}])
    assert out[0]["function"]["arguments"] == {"k": "v"}
    out = normalize_tool_calls([{"name": "x"}])
    assert out[0]["function"]["arguments"] == {}


def test_garbage_and_scalar_arguments_keep_raw_text() -> None:
    for payload in ("totally not json", "3", '"just a string"', "[1, 2,"):
        out = normalize_tool_calls([{"name": "x", "arguments": payload}])
        args = out[0]["function"]["arguments"]
        assert isinstance(args, dict)
        if payload in ("totally not json", "3", '"just a string"', "[1, 2,"):
            # unrecoverable as an OBJECT → original preserved verbatim
            assert args.get("_raw") == payload or "items" in args
        assert out[0]["repaired"] is True
        assert out[0]["arguments_raw"] == payload


def test_malformed_entries_are_skipped_not_crashed() -> None:
    out = normalize_tool_calls([None, "junk", 42, {"name": "keep"}])
    assert len(out) == 1
    assert out[0]["function"]["name"] == "keep"
    assert normalize_tool_calls(None) == []
    assert normalize_tool_calls([]) == []


def test_missing_ids_are_deterministic() -> None:
    out = normalize_tool_calls([{"name": "a"}, {"name": "b"}])
    assert out[0]["id"] == "call_0_a"
    assert out[1]["id"] == "call_1_b"


# --------------------------------------------------------------------------- #
# chat-response normalization
# --------------------------------------------------------------------------- #
def _body(**over):
    base = {
        "choices": [{
            "message": {"role": "assistant", "content": "hi"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }
    base.update(over)
    return base


def test_null_finish_reason_and_missing_usage() -> None:
    body = _body()
    body["choices"][0]["finish_reason"] = None
    del body["usage"]
    res = _parse_chat_response(body, {})
    assert res.finish == "stop"                    # None → default, not "None"
    assert res.usage == {"input": 0, "output": 0}


def test_finish_reason_tool_calls_with_null_content() -> None:
    body = _body()
    body["choices"][0]["message"] = {
        "content": None,
        "tool_calls": [{"id": "c1", "function": {"name": "x",
                                                 "arguments": "{}"}}],
    }
    body["choices"][0]["finish_reason"] = "tool_calls"
    res = _parse_chat_response(body, {})
    assert res.text == ""
    assert res.finish == "tool_calls"
    assert res.tool_calls[0]["function"]["name"] == "x"


def test_list_content_and_provider_reported_cost() -> None:
    body = _body()
    body["choices"][0]["message"]["content"] = [
        {"type": "text", "text": "part one "}, {"type": "text", "text": "part two"}]
    body["cost"] = 0.0042
    res = _parse_chat_response(body, {})
    assert res.text == "part one part two"
    assert res.cost_usd == 0.0042


def test_non_numeric_usage_tokens_coerce_to_zero() -> None:
    body = _body(usage={"prompt_tokens": "12", "completion_tokens": None})
    res = _parse_chat_response(body, {})
    assert res.usage == {"input": 12, "output": 0}
    body = _body(usage={"prompt_tokens": "not-a-number"})
    res = _parse_chat_response(body, {})
    assert res.usage["input"] == 0


def test_empty_choices_is_a_provider_error() -> None:
    with pytest.raises(RouterError) as exc:
        _parse_chat_response({"choices": []}, {})
    assert exc.value.code == "E_PROVIDER_5XX"
    with pytest.raises(RouterError):
        _parse_chat_response({"choices": "not a list"}, {})


def test_usage_cost_field_also_detected() -> None:
    body = _body(usage={"prompt_tokens": 1, "completion_tokens": 1,
                        "cost": 0.0007})
    res = _parse_chat_response(body, {})
    assert res.cost_usd == 0.0007


# --------------------------------------------------------------------------- #
# repair keeps the pipeline honest
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected,repaired", [
    ('{"a": 1}', {"a": 1}, False),          # valid JSON → no repair
    ('{"a": 1,}', {"a": 1}, True),          # trailing comma
    ("{'a': 'b'}", {"a": "b"}, True),       # single quotes
    ('{"a": [1, 2', {"a": [1, 2]}, True),   # truncated stream
])
def test_repair_edge_cases(raw, expected, repaired) -> None:
    args, was_repaired = repair_arguments(raw)
    assert args == expected
    assert was_repaired is repaired
