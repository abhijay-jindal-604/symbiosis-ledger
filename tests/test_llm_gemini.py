"""Exercises llm_gemini's message/tool translation against the real
google-genai SDK types (no network, no API key) -- this is the part most
likely to silently break on an SDK upgrade, since it's the one place this
repo depends on the exact shape of types.Content/Part/FunctionDeclaration.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

from google.genai import types

from llm_gemini import _to_gemini_contents, _to_gemini_tools
from negotiation_agent import TOOL_SPECS


def test_tool_specs_convert_to_valid_function_declarations():
    tools = _to_gemini_tools(types, TOOL_SPECS)
    assert len(tools) == 1
    names = [fd.name for fd in tools[0].function_declarations]
    assert names == ["lookup_receipt_history", "get_receiver_profile", "check_allocation"]


def test_no_tools_converts_to_none():
    assert _to_gemini_tools(types, None) is None
    assert _to_gemini_tools(types, []) is None


def test_user_message_becomes_user_content():
    contents = _to_gemini_contents(types, [{"role": "user", "content": "hello"}])
    assert len(contents) == 1
    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "hello"


def test_assistant_tool_calls_become_model_function_call_content():
    contents = _to_gemini_contents(types, [
        {"role": "assistant", "tool_calls": [
            {"id": "1", "name": "check_allocation", "arguments": {"allocation": []}},
        ]},
    ])
    assert contents[0].role == "model"
    fc = contents[0].parts[0].function_call
    assert fc.name == "check_allocation"
    assert dict(fc.args) == {"allocation": []}


def test_tool_result_becomes_user_role_function_response_content():
    """Regression test for a real 400 INVALID_ARGUMENT hit on gemini-3.6-flash
    and newer ("Role 'tool' is not supported"): gemini-3.5-flash accepts
    Content(role="tool", ...) for a function response (matching the
    python-genai docs' own example), but 3.6+ rejects it and requires
    role="user" instead -- confirmed live against the real API. "user" is
    used here, not "tool", so this must land on a user-role Content."""
    contents = _to_gemini_contents(types, [
        {"role": "tool", "name": "check_allocation", "tool_call_id": "1",
         "content": {"ok": True, "message": "fine"}},
    ])
    assert contents[0].role == "user"
    fr = contents[0].parts[0].function_response
    assert fr.name == "check_allocation"
    assert dict(fr.response) == {"ok": True, "message": "fine"}


def test_unknown_role_raises():
    try:
        _to_gemini_contents(types, [{"role": "system", "content": "x"}])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_assistant_tool_call_with_thought_signature_is_reattached():
    """Regression test for a real 400 INVALID_ARGUMENT hit during this
    project's own second live negotiation run: Gemini 3.5 requires a
    thought_signature to be echoed back on a reconstructed function-call
    turn, and it lives on the Part, not on FunctionCall. Confirms the
    opaque bytes value threaded through the generic tool_call dict as
    "_thought_signature" actually lands back on the reconstructed Part."""
    contents = _to_gemini_contents(types, [
        {"role": "assistant", "tool_calls": [
            {"id": "1", "name": "check_allocation", "arguments": {"allocation": []},
             "_thought_signature": b"opaque-signature-bytes"},
        ]},
    ])
    part = contents[0].parts[0]
    assert part.function_call.name == "check_allocation"
    assert part.thought_signature == b"opaque-signature-bytes"


def test_assistant_tool_call_without_thought_signature_is_still_fine():
    """Older/simpler responses (or fakes in other tests) may not carry a
    signature at all -- must not crash when it's absent."""
    contents = _to_gemini_contents(types, [
        {"role": "assistant", "tool_calls": [
            {"id": "1", "name": "check_allocation", "arguments": {"allocation": []}},
        ]},
    ])
    assert contents[0].parts[0].thought_signature is None
