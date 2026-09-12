"""Tests for negotiate_blind(): the two-call variant where each claimant is
resolved by its own independent call, never seeing the other claimant's
name, request, or disclosed constraint. Mirrors test_negotiation_parse.py's
approach of injecting a fake llm_call(messages, tools) against fixtures.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

from negotiation_agent import negotiate_blind, validate_side_response, NegotiationError
import pytest

CLAIM_A = {"claimant": "kiln-b", "requested_tons": 10, "disclosed_constraint": "needs 10 t continuous"}
CLAIM_B = {"claimant": "wwtp-c", "requested_tons": 14.1325, "disclosed_constraint": "Tue/Thu intake only"}
AVAILABLE = 24.1325


def make_stream(available_tons=AVAILABLE):
    return {
        "stream_id": "TEST-STREAM",
        "waste": {"available_tons": available_tons, "federal_waste_codes": "D009", "form_code": "W301"},
    }


def _side_json(tons, feasible=True, schedule="ok", explanation="ok"):
    return f'{{"feasible": {str(feasible).lower()}, "tons": {tons}, "schedule": "{schedule}", "explanation": "{explanation}"}}'


# --- validate_side_response ---

def test_side_response_with_valid_tons_is_feasible():
    normalized = validate_side_response({"feasible": True, "tons": 5, "schedule": "x", "explanation": "y"}, AVAILABLE)
    assert normalized["feasible"] is True
    assert normalized["tons"] == 5.0


def test_side_response_infeasible_with_no_tons_is_allowed():
    normalized = validate_side_response({"feasible": False, "explanation": "no usable constraint"}, AVAILABLE)
    assert normalized["feasible"] is False
    assert normalized["tons"] is None


def test_side_response_missing_tons_without_feasible_false_raises():
    with pytest.raises(NegotiationError):
        validate_side_response({"explanation": "y"}, AVAILABLE)


def test_side_response_tons_over_available_raises():
    with pytest.raises(NegotiationError):
        validate_side_response({"feasible": True, "tons": 999, "explanation": "y"}, AVAILABLE)


def test_side_response_negative_tons_raises():
    with pytest.raises(NegotiationError):
        validate_side_response({"feasible": True, "tons": -1, "explanation": "y"}, AVAILABLE)


# --- negotiate_blind(): neither call sees the other's request/constraint ---

def test_neither_call_ever_mentions_the_other_claimants_constraint():
    seen_prompts = []

    def fake_llm(messages, tools):
        seen_prompts.append(messages[0]["content"])
        if "kiln-b" in messages[0]["content"]:
            return {"text": _side_json(10)}
        return {"text": _side_json(14.1325)}

    result = negotiate_blind(make_stream(), CLAIM_A, CLAIM_B, fake_llm)
    assert result["status"] == "RESOLVED_SPLIT"
    assert len(seen_prompts) == 2
    # kiln-b's own call must never see wwtp-c's constraint text, and vice versa.
    for prompt in seen_prompts:
        assert "Tue/Thu intake only" not in prompt or "kiln-b" not in prompt
        assert "needs 10 t continuous" not in prompt or "wwtp-c" not in prompt


def test_both_feasible_and_fitting_resolves_split_in_one_round():
    def fake_llm(messages, tools):
        if "kiln-b" in messages[0]["content"]:
            return {"text": _side_json(10)}
        return {"text": _side_json(14.1325)}

    result = negotiate_blind(make_stream(), CLAIM_A, CLAIM_B, fake_llm)
    assert result["status"] == "RESOLVED_SPLIT"
    assert result["method"] == "negotiated_split_blind"
    tons_by_claimant = {e["claimant"]: e["tons"] for e in result["allocation"]}
    assert tons_by_claimant["kiln-b"] == 10.0
    assert tons_by_claimant["wwtp-c"] == 14.1325


def test_oversubscribed_first_round_triggers_a_second_round():
    calls = {"kiln-b": 0, "wwtp-c": 0}

    def fake_llm(messages, tools):
        content = messages[0]["content"]
        if "kiln-b" in content:
            calls["kiln-b"] += 1
            if calls["kiln-b"] == 1:
                return {"text": _side_json(20)}  # round 1: too much
            return {"text": _side_json(10)}  # round 2: revised down
        else:
            calls["wwtp-c"] += 1
            if calls["wwtp-c"] == 1:
                return {"text": _side_json(20)}
            return {"text": _side_json(14.1325)}

    result = negotiate_blind(make_stream(), CLAIM_A, CLAIM_B, fake_llm)
    assert calls["kiln-b"] == 2
    assert calls["wwtp-c"] == 2
    assert result["status"] == "RESOLVED_SPLIT"
    # the round-2 prompt must disclose only the numeric shortfall, not the other side's identity
    assert result["method"] == "negotiated_split_blind"


def test_second_round_note_never_names_the_other_claimant():
    prompts = []

    def fake_llm(messages, tools):
        prompts.append(messages[0]["content"])
        n = len(prompts)
        if "kiln-b" in messages[0]["content"]:
            return {"text": _side_json(20 if n <= 2 else 10)}
        return {"text": _side_json(20 if n <= 2 else 14.1325)}

    negotiate_blind(make_stream(), CLAIM_A, CLAIM_B, fake_llm)
    round_2_prompts = [p for p in prompts if "second, independent facility" in p]
    assert len(round_2_prompts) == 2
    for p in round_2_prompts:
        assert "kiln-b" not in p.split("second, independent facility")[1].split("shortfall")[0]
        assert "wwtp-c" not in p.split("second, independent facility")[1].split("shortfall")[0]


def test_still_oversubscribed_after_second_round_is_prorated_not_a_coin_flip():
    def fake_llm(messages, tools):
        # both sides refuse to budge across both rounds
        if "kiln-b" in messages[0]["content"]:
            return {"text": _side_json(20)}
        return {"text": _side_json(20)}

    result = negotiate_blind(make_stream(), CLAIM_A, CLAIM_B, fake_llm)
    assert result["status"] == "RESOLVED_PARTIAL"
    assert result["method"] == "negotiated_partial_blind_prorated"
    tons_by_claimant = {e["claimant"]: e["tons"] for e in result["allocation"]}
    # 20/20 requested, scaled proportionally (even split, since requests were equal)
    assert tons_by_claimant["kiln-b"] == pytest.approx(AVAILABLE / 2, rel=1e-6)
    assert tons_by_claimant["wwtp-c"] == pytest.approx(AVAILABLE / 2, rel=1e-6)
    total = sum(e["tons"] for e in result["allocation"])
    assert total == pytest.approx(AVAILABLE, rel=1e-6)


def test_one_side_infeasible_is_not_asked_to_revise_in_round_two():
    calls = {"kiln-b": 0}

    def fake_llm(messages, tools):
        if "kiln-b" in messages[0]["content"]:
            calls["kiln-b"] += 1
            return {"text": '{"feasible": false, "explanation": "constraint has no usable number"}'}
        return {"text": _side_json(20)}  # oversubscribed vs. kiln-b's 0, forces round 2 for wwtp-c only

    result = negotiate_blind(make_stream(), CLAIM_A, CLAIM_B, fake_llm)
    assert calls["kiln-b"] == 1  # never re-asked: nothing to revise from an infeasible side
    assert result["status"] == "RESOLVED_PARTIAL"
    tons_by_claimant = {e["claimant"]: e["tons"] for e in result["allocation"]}
    assert tons_by_claimant["kiln-b"] == 0.0


def test_unanswerable_before_calling_model():
    def should_not_be_called(messages, tools):
        raise AssertionError("model should not be called when available_tons <= 0")

    result = negotiate_blind(make_stream(available_tons=0), CLAIM_A, CLAIM_B, should_not_be_called)
    assert result["status"] == "UNRESOLVED"


def test_falls_back_deterministically_when_model_path_never_produces_valid_json():
    def always_bad(messages, tools):
        return {"text": "not json at all"}

    result = negotiate_blind(make_stream(), CLAIM_A, CLAIM_B, always_bad, max_content_retries=0)
    tons_by_claimant = {e["claimant"]: e["tons"] for e in result["allocation"]}
    # fallback takes each side's stated request at face value, then reconciles
    assert tons_by_claimant["kiln-b"] + tons_by_claimant["wwtp-c"] <= AVAILABLE + 0.01


def test_negotiate_blind_writes_a_log_with_both_rounds(tmp_path):
    def fake_llm(messages, tools):
        content = messages[0]["content"]
        n = sum(1 for c in [content] if True)
        if "kiln-b" in content:
            return {"text": _side_json(20 if "shortfall" not in content else 10)}
        return {"text": _side_json(20 if "shortfall" not in content else 14.1325)}

    log_path = str(tmp_path / "log.json")
    negotiate_blind(make_stream(), CLAIM_A, CLAIM_B, fake_llm, log_path=log_path)
    import json
    with open(log_path) as f:
        payload = json.load(f)
    assert payload["protocol"] == "two_call_blind"
    assert payload["rounds_used"] == 2
    assert "kiln-b" in payload["attempts"]["round_1"]
    assert "kiln-b" in payload["attempts"]["round_2"]
