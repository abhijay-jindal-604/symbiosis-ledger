"""Fixture suite for the negotiation agent's response handling: one test
per row of CONTEXT-DUMP.md §6's failure matrix. This is what lets the
negotiation agent be built and validated before a real repo/PRs exist.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

import pytest
from negotiation_agent import (
    extract_json_span, validate_response, negotiate, NegotiationError,
)

CLAIM_A = {"claimant": "kiln-b", "requested_tons": 15, "disclosed_constraint": "needs 15 t continuous"}
CLAIM_B = {"claimant": "wwtp-c", "requested_tons": 24.1325, "disclosed_constraint": "Tue/Thu intake only"}
AVAILABLE = 24.1325


def make_stream(available_tons=AVAILABLE):
    return {
        "stream_id": "TEST-STREAM",
        "waste": {"available_tons": available_tons, "federal_waste_codes": "D009", "form_code": "W301"},
    }


# --- extraction ---

def test_clean_json_object():
    raw = '{"feasible": true, "allocation": [{"claimant": "kiln-b", "tons": 10, "schedule": "cont"}, {"claimant": "wwtp-c", "tons": 14.1325, "schedule": "Tue/Thu"}], "explanation": "ok"}'
    span = extract_json_span(raw)
    import json
    parsed = json.loads(span)
    status, normalized = validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)
    assert status == "accepted"


def test_json_wrapped_in_fences_and_prose():
    raw = 'Sure, here you go:\n```json\n{"feasible": true, "allocation": [{"claimant": "kiln-b", "tons": 10, "schedule": "cont"}, {"claimant": "wwtp-c", "tons": 14, "schedule": "Tue/Thu"}], "explanation": "ok"}\n```\nHope that helps!'
    span = extract_json_span(raw)
    import json
    parsed = json.loads(span)
    status, _ = validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)
    assert status == "accepted"


def test_tons_as_string_with_unit_coerced():
    entry = {"claimant": "kiln-b", "tons": "10 t", "schedule": "cont"}
    parsed = {"feasible": True, "allocation": [entry, {"claimant": "wwtp-c", "tons": "14", "schedule": "Tue/Thu"}], "explanation": "ok"}
    status, normalized = validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)
    assert status == "accepted"
    tons_by_claimant = {e["claimant"]: e["tons"] for e in normalized["allocation"]}
    assert tons_by_claimant["kiln-b"] == 10.0


def test_tons_as_range_is_invalid():
    parsed = {"feasible": True, "allocation": [{"claimant": "kiln-b", "tons": "30-50", "schedule": "cont"}, {"claimant": "wwtp-c", "tons": 5, "schedule": "x"}], "explanation": "ok"}
    with pytest.raises(NegotiationError):
        validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)


def test_allocation_oversum_is_invalid():
    parsed = {"feasible": True, "allocation": [{"claimant": "kiln-b", "tons": 20, "schedule": "cont"}, {"claimant": "wwtp-c", "tons": 20, "schedule": "x"}], "explanation": "ok"}
    with pytest.raises(NegotiationError):
        validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)


def test_allocation_undersum_is_valid():
    parsed = {"feasible": True, "allocation": [{"claimant": "kiln-b", "tons": 5, "schedule": "cont"}, {"claimant": "wwtp-c", "tons": 5, "schedule": "x"}], "explanation": "leaves a remainder unclaimed"}
    status, normalized = validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)
    assert status == "accepted"


def test_negative_tons_is_invalid():
    parsed = {"feasible": True, "allocation": [{"claimant": "kiln-b", "tons": -5, "schedule": "cont"}, {"claimant": "wwtp-c", "tons": 20, "schedule": "x"}], "explanation": "ok"}
    with pytest.raises(NegotiationError):
        validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)


def test_three_claimants_is_invalid():
    parsed = {"feasible": True, "allocation": [
        {"claimant": "kiln-b", "tons": 5, "schedule": "cont"},
        {"claimant": "wwtp-c", "tons": 5, "schedule": "x"},
        {"claimant": "recycler-d", "tons": 5, "schedule": "y"},
    ], "explanation": "ok"}
    with pytest.raises(NegotiationError):
        validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)


def test_duplicate_claimant_is_invalid():
    parsed = {"feasible": True, "allocation": [
        {"claimant": "kiln-b", "tons": 5, "schedule": "cont"},
        {"claimant": "kiln-b", "tons": 5, "schedule": "cont"},
    ], "explanation": "ok"}
    with pytest.raises(NegotiationError):
        validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)


def test_missing_claimant_is_invalid():
    parsed = {"feasible": True, "allocation": [{"claimant": "kiln-b", "tons": 5, "schedule": "cont"}], "explanation": "ok"}
    with pytest.raises(NegotiationError):
        validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)


def test_unknown_claimant_name_is_invalid():
    parsed = {"feasible": True, "allocation": [
        {"claimant": "kiln-b", "tons": 5, "schedule": "cont"},
        {"claimant": "some-other-facility", "tons": 5, "schedule": "x"},
    ], "explanation": "ok"}
    with pytest.raises(NegotiationError):
        validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)


def test_feasible_false_with_valid_allocation_is_accepted_as_partial():
    parsed = {"feasible": False, "allocation": [
        {"claimant": "kiln-b", "tons": 15, "schedule": "cont"},
        {"claimant": "wwtp-c", "tons": 5, "schedule": "Tue only"},
    ], "explanation": "wwtp-c can only take 5t within its window; the rest is unclaimed"}
    status, normalized = validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)
    assert status == "rejected_partial_but_valid_becomes_accepted_partial"


def test_feasible_false_with_empty_allocation_is_unresolved():
    parsed = {"feasible": False, "allocation": [], "explanation": "wwtp-c's disclosed constraint has no quantity or schedule I can act on"}
    status, normalized = validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)
    assert status == "rejected_unresolved"


def test_empty_constraint_response_does_not_invent_a_number():
    # This is the failure mode the arithmetic check cannot catch on its own,
    # so it's the prompt's job to produce feasible:false rather than a summed
    # allocation. Verify the harness correctly accepts a well-behaved refusal
    # rather than silently accepting an invented number.
    parsed = {"feasible": False, "allocation": [], "explanation": "claimant B's disclosed constraint is empty; cannot allocate without inventing a number"}
    status, _ = validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)
    assert status == "rejected_unresolved"


def test_feasible_missing_entirely_inferred_from_allocation():
    parsed = {"allocation": [
        {"claimant": "kiln-b", "tons": 10, "schedule": "cont"},
        {"claimant": "wwtp-c", "tons": 14, "schedule": "Tue/Thu"},
    ], "explanation": "ok"}
    status, _ = validate_response(parsed, CLAIM_A, CLAIM_B, AVAILABLE)
    assert status == "accepted"


def test_truncated_json_raises_on_extraction():
    raw = '{"feasible": true, "allocation": [{"claimant": "kiln-b", "tons": 10'
    with pytest.raises(NegotiationError):
        extract_json_span(raw)


def test_no_json_at_all_raises_on_extraction():
    raw = "I cannot help with that request."
    with pytest.raises(NegotiationError):
        extract_json_span(raw)


# --- end-to-end negotiate() with an injected fake llm_call(messages, tools) ---

SPLIT_JSON = ('{"feasible": true, "allocation": '
              '[{"claimant": "kiln-b", "tons": 10, "schedule": "cont"}, '
              '{"claimant": "wwtp-c", "tons": 14.1325, "schedule": "Tue/Thu"}], '
              '"explanation": "fits both"}')


def test_negotiate_happy_path_no_tool_calls():
    def fake_llm(messages, tools):
        return {"text": SPLIT_JSON}
    result = negotiate(make_stream(), CLAIM_A, CLAIM_B, fake_llm)
    assert result["status"] == "RESOLVED_SPLIT"
    assert result["method"] == "negotiated_split"


def test_negotiate_retries_with_specific_violation_then_succeeds():
    calls = []

    def fake_llm(messages, tools):
        calls.append(messages)
        if len(calls) == 1:
            return {"text": '{"feasible": true, "allocation": [{"claimant": "kiln-b", "tons": 20, "schedule": "cont"}, {"claimant": "wwtp-c", "tons": 20, "schedule": "x"}], "explanation": "ok"}'}
        return {"text": '{"feasible": true, "allocation": [{"claimant": "kiln-b", "tons": 10, "schedule": "cont"}, {"claimant": "wwtp-c", "tons": 14, "schedule": "Tue/Thu"}], "explanation": "corrected"}'}

    result = negotiate(make_stream(), CLAIM_A, CLAIM_B, fake_llm)
    assert result["status"] == "RESOLVED_SPLIT"
    assert len(calls) == 2
    assert "rejected" in calls[1][0]["content"]  # retry prompt names the specific violation


def test_negotiate_falls_back_after_exhausting_content_retries():
    def always_bad(messages, tools):
        return {"text": '{"feasible": true, "allocation": [{"claimant": "kiln-b", "tons": 999, "schedule": "cont"}]}'}

    result = negotiate(make_stream(), CLAIM_A, CLAIM_B, always_bad, max_content_retries=1)
    assert result["status"] == "RESOLVED_EVEN_SPLIT_FALLBACK"
    assert result["method"] == "deterministic_fallback"


def test_negotiate_api_error_retry_budget_separate_from_content_retry():
    calls = {"n": 0}

    def flaky_then_ok(messages, tools):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise ConnectionError("simulated 5xx")
        return {"text": SPLIT_JSON}

    result = negotiate(make_stream(), CLAIM_A, CLAIM_B, flaky_then_ok, api_backoff=(0, 0))
    assert result["status"] == "RESOLVED_SPLIT"


def test_negotiate_unanswerable_before_calling_model():
    def should_not_be_called(messages, tools):
        raise AssertionError("model should not be called when available_tons <= 0")

    result = negotiate(make_stream(available_tons=0), CLAIM_A, CLAIM_B, should_not_be_called)
    assert result["status"] == "UNRESOLVED"


# --- the tool-calling loop itself ---

def test_negotiate_calls_check_allocation_tool_then_finalizes():
    """The model self-checks its proposed split via the check_allocation tool
    before returning its final answer -- this is the actual agentic loop,
    not just a single prompt/response round-trip."""
    turns = []

    def fake_llm(messages, tools):
        turns.append(messages)
        assert tools is not None and any(t["name"] == "check_allocation" for t in tools)
        if len(turns) == 1:
            return {"tool_calls": [{
                "id": "call-1", "name": "check_allocation",
                "arguments": {"allocation": [{"claimant": "kiln-b", "tons": 10},
                                              {"claimant": "wwtp-c", "tons": 14.1325}]},
            }]}
        # second turn: the tool result should now be in the message history
        assert messages[-1]["role"] == "tool"
        assert messages[-1]["content"]["ok"] is True
        return {"text": SPLIT_JSON}

    result = negotiate(make_stream(), CLAIM_A, CLAIM_B, fake_llm)
    assert result["status"] == "RESOLVED_SPLIT"
    assert len(turns) == 2


def test_negotiate_check_allocation_tool_catches_overallocation():
    def fake_llm(messages, tools):
        if len(messages) == 1:
            return {"tool_calls": [{
                "id": "call-1", "name": "check_allocation",
                "arguments": {"allocation": [{"claimant": "kiln-b", "tons": 100},
                                              {"claimant": "wwtp-c", "tons": 100}]},
            }]}
        assert messages[-1]["content"]["ok"] is False
        assert "exceeds available" in messages[-1]["content"]["message"]
        return {"text": SPLIT_JSON}

    result = negotiate(make_stream(), CLAIM_A, CLAIM_B, fake_llm)
    assert result["status"] == "RESOLVED_SPLIT"


def test_negotiate_lookup_receipt_history_tool_is_wired_through():
    seen = {}

    def fake_lookup(claimant):
        seen["claimant"] = claimant
        return {"eligible": True, "message": f"{claimant} has real recovery history"}

    def fake_llm(messages, tools):
        if len(messages) == 1:
            return {"tool_calls": [{"id": "call-1", "name": "lookup_receipt_history",
                                     "arguments": {"claimant": "kiln-b"}}]}
        assert messages[-1]["content"]["eligible"] is True
        return {"text": SPLIT_JSON}

    result = negotiate(make_stream(), CLAIM_A, CLAIM_B, fake_llm,
                        lookup_receipt_history=fake_lookup)
    assert result["status"] == "RESOLVED_SPLIT"
    assert seen["claimant"] == "kiln-b"


def test_negotiate_get_receiver_profile_tool_is_wired_through():
    def fake_profile(claimant):
        return {"accepted_streams": ["OTHER-STREAM"], "rejected_claims": []}

    def fake_llm(messages, tools):
        if len(messages) == 1:
            return {"tool_calls": [{"id": "call-1", "name": "get_receiver_profile",
                                     "arguments": {"claimant": "wwtp-c"}}]}
        assert "OTHER-STREAM" in messages[-1]["content"]["accepted_streams"]
        return {"text": SPLIT_JSON}

    result = negotiate(make_stream(), CLAIM_A, CLAIM_B, fake_llm,
                        get_receiver_profile=fake_profile)
    assert result["status"] == "RESOLVED_SPLIT"


def test_negotiate_gives_up_after_max_tool_turns_without_final_answer():
    def never_finishes(messages, tools):
        return {"tool_calls": [{"id": "x", "name": "check_allocation", "arguments": {"allocation": []}}]}

    result = negotiate(make_stream(), CLAIM_A, CLAIM_B, never_finishes,
                        max_content_retries=0, max_tool_turns=2)
    assert result["status"] == "RESOLVED_EVEN_SPLIT_FALLBACK"


def test_negotiate_unknown_tool_name_returns_error_to_model_without_crashing():
    def fake_llm(messages, tools):
        if len(messages) == 1:
            return {"tool_calls": [{"id": "x", "name": "not_a_real_tool", "arguments": {}}]}
        assert "error" in messages[-1]["content"]
        return {"text": SPLIT_JSON}

    result = negotiate(make_stream(), CLAIM_A, CLAIM_B, fake_llm)
    assert result["status"] == "RESOLVED_SPLIT"
