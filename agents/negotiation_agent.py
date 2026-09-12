"""The negotiation agent: the one hard thing. Given two claims on the same
stream, each carrying a disclosed_constraint the other claimant's claim
never mentions, compute a split allocation via a single LLM call. Pure
function of its inputs (no file writes) so it can be unit-tested against
fixtures without touching git or the filesystem.
"""
import json
import os
import time

PROMPT_TEMPLATE = """You are resolving a conflict between two facilities that both want the same industrial byproduct stream.

Stream: {stream_id}
Available: {available_tons} tons of waste code {federal_waste_codes} (form {form_code})

Claimant A: {claimant_a}
  Requested: {requested_tons_a} tons
  Disclosed constraint: "{disclosed_constraint_a}"

Claimant B: {claimant_b}
  Requested: {requested_tons_b} tons
  Disclosed constraint: "{disclosed_constraint_b}"

Propose a split allocation (tons and scheduling terms for each claimant) that satisfies both
disclosed constraints if a satisfying split exists. If no split satisfies both fully, say so
and propose the largest feasible allocation to each within their own stated constraint,
explaining the shortfall in one sentence.

Rules you must follow:
- Include exactly one entry per claimant, using the claimant names exactly as given above.
- "tons" must be a bare number (no units, no ranges, no strings), >= 0.
- The tons across all entries must sum to at most {available_tons}.
- If a disclosed constraint is empty, vague, or states no quantity or schedule you can act on,
  do NOT invent a number for it: set "feasible" to false and name that constraint in the
  explanation as the reason.
- Output the JSON object and nothing else: no prose, no markdown code fences, no commentary.

Return strict JSON only:
{{"feasible": true|false, "allocation": [{{"claimant": "...", "tons": N, "schedule": "..."}}], "explanation": "..."}}"""


class NegotiationError(Exception):
    pass


def build_prompt(stream, claim_a, claim_b):
    return PROMPT_TEMPLATE.format(
        stream_id=stream["stream_id"],
        available_tons=stream["waste"]["available_tons"],
        federal_waste_codes=stream["waste"]["federal_waste_codes"],
        form_code=stream["waste"]["form_code"],
        claimant_a=claim_a["claimant"],
        requested_tons_a=claim_a["requested_tons"],
        disclosed_constraint_a=claim_a.get("disclosed_constraint", ""),
        claimant_b=claim_b["claimant"],
        requested_tons_b=claim_b["requested_tons"],
        disclosed_constraint_b=claim_b.get("disclosed_constraint", ""),
    )


def extract_json_span(text):
    """Extract the first balanced {...} span by brace-counting. Raises
    NegotiationError if none found."""
    start = text.find("{")
    if start == -1:
        raise NegotiationError("no JSON object found in response")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise NegotiationError("truncated JSON: no balanced closing brace found")


def _coerce_tons(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = "".join(ch for ch in value if ch.isdigit() or ch in ".-")
        if stripped in ("", "-", "."):
            raise NegotiationError(f"tons value {value!r} is not a number")
        if "-" in stripped[1:]:
            raise NegotiationError(f"tons value {value!r} looks like a range")
        return float(stripped)
    raise NegotiationError(f"tons value {value!r} has unsupported type {type(value)}")


def validate_response(parsed, claim_a, claim_b, available_tons):
    """Validate a parsed response dict against the failure matrix.
    Returns (status, normalized) where status is one of:
    'accepted_full', 'accepted_partial', 'rejected'.
    Raises NegotiationError with a specific reason on rejection (caller
    decides whether that's retry-worthy)."""
    if not isinstance(parsed, dict):
        raise NegotiationError("response is not a JSON object")

    allocation = parsed.get("allocation")
    feasible = parsed.get("feasible")

    if allocation is None:
        allocation = []
    if not isinstance(allocation, list):
        raise NegotiationError("allocation is not a list")

    valid_names = {claim_a["claimant"].strip().lower(), claim_b["claimant"].strip().lower()}
    name_map = {claim_a["claimant"].strip().lower(): claim_a["claimant"],
                claim_b["claimant"].strip().lower(): claim_b["claimant"]}

    if feasible is False and not allocation:
        return "rejected_unresolved", parsed

    if allocation:
        seen = set()
        normalized = []
        total = 0.0
        for entry in allocation:
            if not isinstance(entry, dict) or "claimant" not in entry or "tons" not in entry:
                raise NegotiationError("allocation entry missing claimant or tons")
            name_key = str(entry["claimant"]).strip().lower()
            if name_key not in valid_names:
                raise NegotiationError(f"unknown claimant name '{entry['claimant']}' in allocation")
            if name_key in seen:
                raise NegotiationError(f"duplicate claimant '{entry['claimant']}' in allocation")
            seen.add(name_key)
            tons = _coerce_tons(entry["tons"])
            if tons < 0:
                raise NegotiationError(f"negative tons ({tons}) for claimant '{entry['claimant']}'")
            total += tons
            normalized.append({
                "claimant": name_map[name_key],
                "tons": tons,
                "schedule": entry.get("schedule", ""),
            })

        if len(seen) != 2:
            raise NegotiationError(f"expected exactly 2 claimants in allocation, got {len(seen)}")

        if total > available_tons + 0.01:
            raise NegotiationError(
                f"allocation summed to {total} tons but only {available_tons} are available"
            )

        parsed["allocation"] = normalized
        if feasible is False:
            return "rejected_partial_but_valid_becomes_accepted_partial", parsed
        return "accepted", parsed

    if feasible is None:
        raise NegotiationError("feasible missing and allocation empty/invalid")

    return "rejected_unresolved", parsed


def resolve_status_and_method(validation_status):
    if validation_status == "accepted":
        return "RESOLVED_SPLIT", "negotiated_split"
    if validation_status == "rejected_partial_but_valid_becomes_accepted_partial":
        return "RESOLVED_PARTIAL", "negotiated_partial"
    return "UNRESOLVED", None


def deterministic_even_split(claim_a, claim_b, available_tons):
    half = available_tons / 2.0
    return {
        "feasible": True,
        "allocation": [
            {"claimant": claim_a["claimant"], "tons": half, "schedule": "even split (fallback)"},
            {"claimant": claim_b["claimant"], "tons": half, "schedule": "even split (fallback)"},
        ],
        "explanation": "Deterministic even-split fallback: the model path failed after its retry budget.",
    }


def negotiate(stream, claim_a, claim_b, llm_call, log_path=None, max_content_retries=1,
              max_api_retries=2, api_backoff=(2, 6)):
    """llm_call(prompt: str) -> str (raw model text). Injected so this stays
    a pure function testable against fixtures without a real API key."""
    available_tons = stream["waste"]["available_tons"]
    attempts = []
    path_taken = "primary"

    if available_tons is None or available_tons <= 0 or "requested_tons" not in claim_a \
            or "requested_tons" not in claim_b:
        result = {
            "status": "UNRESOLVED", "method": None, "resolved_by": None,
            "feasible": False, "explanation": "available_tons <= 0 or requested_tons missing; "
            "not calling the model.",
        }
        _write_log(log_path, stream["stream_id"], attempts, "unanswerable", "UNRESOLVED")
        return result

    prompt = build_prompt(stream, claim_a, claim_b)
    last_error = None

    for content_attempt in range(max_content_retries + 1):
        this_prompt = prompt if content_attempt == 0 else (
            prompt + f'\n\nYour previous response was rejected: {last_error} '
            "Return corrected strict JSON."
        )
        raw = None
        for api_attempt in range(max_api_retries + 1):
            try:
                raw = llm_call(this_prompt)
                break
            except Exception as e:  # network/API error budget, separate from content retries
                if api_attempt >= max_api_retries:
                    raw = None
                    last_error = f"API error: {e}"
                    break
                time.sleep(api_backoff[min(api_attempt, len(api_backoff) - 1)])

        if raw is None:
            attempts.append({"n": len(attempts) + 1, "prompt": this_prompt, "raw_response": None,
                              "outcome": "api_error", "reason": last_error})
            continue

        try:
            span = extract_json_span(raw)
            parsed = json.loads(span)
            status, normalized = validate_response(parsed, claim_a, claim_b, available_tons)
            attempts.append({"n": len(attempts) + 1, "prompt": this_prompt, "raw_response": raw,
                              "outcome": "accepted", "reason": None})
            resolution_status, method = resolve_status_and_method(status)
            path_taken = "primary" if content_attempt == 0 else "retry"
            result = {
                "status": resolution_status,
                "method": method,
                "resolved_by": "negotiation_agent_v1" if method else None,
                "feasible": normalized.get("feasible", status == "accepted"),
                "explanation": normalized.get("explanation", ""),
                "allocation": normalized.get("allocation", []),
            }
            _write_log(log_path, stream["stream_id"], attempts, path_taken, resolution_status)
            return result
        except NegotiationError as e:
            last_error = str(e)
            attempts.append({"n": len(attempts) + 1, "prompt": this_prompt, "raw_response": raw,
                              "outcome": "rejected", "reason": last_error})
            continue

    # Exhausted content retries: deterministic fallback
    fallback = deterministic_even_split(claim_a, claim_b, available_tons)
    result = {
        "status": "RESOLVED_EVEN_SPLIT_FALLBACK",
        "method": "deterministic_fallback",
        "resolved_by": "fallback_even_split_v1",
        "feasible": True,
        "explanation": fallback["explanation"],
        "allocation": fallback["allocation"],
    }
    _write_log(log_path, stream["stream_id"], attempts, "deterministic_fallback",
               "RESOLVED_EVEN_SPLIT_FALLBACK")
    return result


def _write_log(log_path, stream_id, attempts, path_taken, final_status):
    if not log_path:
        return
    payload = {
        "stream_id": stream_id,
        "model": os.environ.get("NEGOTIATION_MODEL", "unknown"),
        "temperature": 0,
        "attempts": attempts,
        "path_taken": path_taken,
        "final_status": final_status,
    }
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(payload, f, indent=2)
