"""The negotiation agent: the one hard thing. Given two claims on the same
stream, each carrying a disclosed_constraint the other claimant's claim
never mentions, resolve a split allocation via a real tool-calling loop:
the model can look up each claimant's actual receipt history, its own
memory profile, and self-check a candidate allocation's arithmetic before
committing to a final answer -- rather than being handed every fact
pre-digested in one prompt and asked to guess at the arithmetic blind.

Pure function of its inputs (no file writes, no network calls of its own):
llm_call and the two lookup callables are all injected, so this stays
unit-testable against fixtures without touching git, the filesystem, or a
real API key.
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

You have three tools available:
- lookup_receipt_history(claimant): see the real recorded receipt history behind that claimant's
  eligibility, rather than taking eligibility on faith.
- get_receiver_profile(claimant): see a claimant's own prior acceptances/rejections in this system,
  so you don't repeat a decision this system already settled.
- check_allocation(allocation): verify a candidate split is arithmetically valid (no negative tons,
  total <= available) BEFORE you commit to it as your final answer, so you catch your own mistake
  instead of being rejected and having to retry.

Use any of these tools if they would help, in any order, as many times as you need -- or none at
all if you don't need them. When you are ready, propose a split allocation (tons and scheduling
terms for each claimant) that satisfies both disclosed constraints if a satisfying split exists.
If no split satisfies both fully, say so and propose the largest feasible allocation to each
within their own stated constraint, explaining the shortfall in one sentence.

Rules for your final answer:
- Include exactly one entry per claimant, using the claimant names exactly as given above.
- "tons" must be a bare number (no units, no ranges, no strings), >= 0.
- The tons across all entries must sum to at most {available_tons}.
- If a disclosed constraint is empty, vague, or states no quantity or schedule you can act on,
  do NOT invent a number for it: set "feasible" to false and name that constraint in the
  explanation as the reason.
- Once you are done calling tools, your final response must be the JSON object and nothing else:
  no prose, no markdown code fences, no commentary, no further tool calls.

Final answer format, strict JSON only:
{{"feasible": true|false, "allocation": [{{"claimant": "...", "tons": N, "schedule": "..."}}], "explanation": "..."}}"""

TOOL_SPECS = [
    {
        "name": "lookup_receipt_history",
        "description": (
            "Look up whether a named claimant has a real recorded receipt history for this "
            "stream's waste code under a recovery-type management method. This is the same "
            "eligibility fact the CI gate already checked before this claim could reach "
            "negotiation -- call this to see the underlying reason for yourself."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "claimant": {"type": "string", "description": "Exact claimant name, e.g. 'kiln-b'"},
            },
            "required": ["claimant"],
        },
    },
    {
        "name": "get_receiver_profile",
        "description": (
            "Look up a claimant's own prior history with this system: streams it has previously "
            "been allocated, and streams/claims it was previously rejected for and why. Use this "
            "to avoid repeating a past mistake or re-litigating a settled rejection."
        ),
        "parameters": {
            "type": "object",
            "properties": {"claimant": {"type": "string"}},
            "required": ["claimant"],
        },
    },
    {
        "name": "check_allocation",
        "description": (
            "Check whether a candidate allocation (a list of {claimant, tons}) is arithmetically "
            "valid for this stream: no negative tons, and the total does not exceed the tons "
            "available. Call this on your proposed split before returning it as your final answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "allocation": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claimant": {"type": "string"},
                            "tons": {"type": "number"},
                        },
                        "required": ["claimant", "tons"],
                    },
                },
            },
            "required": ["allocation"],
        },
    },
]


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


# --- tool execution -----------------------------------------------------

def _default_lookup_receipt_history(claimant):
    return {"available": False, "message": "lookup_receipt_history is not available in this context"}


def _default_get_receiver_profile(claimant):
    return {"available": False, "message": "get_receiver_profile is not available in this context"}


def _check_allocation_tool(allocation, available_tons):
    if not isinstance(allocation, list):
        return {"ok": False, "message": "allocation must be a list of {claimant, tons}"}
    total = 0.0
    for entry in allocation:
        if not isinstance(entry, dict) or "tons" not in entry:
            return {"ok": False, "message": f"malformed allocation entry: {entry!r}"}
        try:
            tons = _coerce_tons(entry["tons"])
        except NegotiationError as e:
            return {"ok": False, "message": str(e)}
        if tons < 0:
            return {"ok": False, "message": f"negative tons ({tons}) for {entry.get('claimant')!r}"}
        total += tons
    if total > available_tons + 0.01:
        return {"ok": False, "message": f"allocation sums to {total}, exceeds available {available_tons}"}
    return {"ok": True, "message": f"allocation sums to {total}, within available {available_tons}"}


def _execute_tool(name, arguments, ctx):
    arguments = arguments or {}
    if name == "lookup_receipt_history":
        return ctx["lookup_receipt_history"](arguments.get("claimant"))
    if name == "get_receiver_profile":
        return ctx["get_receiver_profile"](arguments.get("claimant"))
    if name == "check_allocation":
        return _check_allocation_tool(arguments.get("allocation"), ctx["available_tons"])
    return {"error": f"unknown tool '{name}'"}


def _call_with_api_retries(llm_call, messages, tools, max_api_retries, api_backoff):
    """Returns (response, error). error is None on success; on exhausted
    retries, response is None and error carries the last exception."""
    err = None
    for api_attempt in range(max_api_retries + 1):
        try:
            return llm_call(messages, tools), None
        except Exception as e:  # network/API error budget, separate from content retries
            err = e
            if api_attempt >= max_api_retries:
                return None, err
            time.sleep(api_backoff[min(api_attempt, len(api_backoff) - 1)])
    return None, err


# --- the main entry point ------------------------------------------------

def negotiate(stream, claim_a, claim_b, llm_call, lookup_receipt_history=None,
              get_receiver_profile=None, log_path=None, max_content_retries=1,
              max_api_retries=2, api_backoff=(2, 6), max_tool_turns=6):
    """llm_call(messages, tools) -> {"tool_calls": [{"id","name","arguments"}]} or {"text": str}.
    Injected so this stays a pure function testable against fixtures without a real API key.

    lookup_receipt_history(claimant) -> dict and get_receiver_profile(claimant) -> dict are the
    two side-effecting lookups the model can request as tools; injected for the same reason.
    """
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

    ctx = {
        "available_tons": available_tons,
        "lookup_receipt_history": lookup_receipt_history or _default_lookup_receipt_history,
        "get_receiver_profile": get_receiver_profile or _default_get_receiver_profile,
    }

    base_prompt = build_prompt(stream, claim_a, claim_b)
    last_error = None

    for content_attempt in range(max_content_retries + 1):
        opening = base_prompt if content_attempt == 0 else (
            base_prompt + f'\n\nYour previous response was rejected: {last_error} '
            "Return corrected strict JSON as your final answer."
        )
        messages = [{"role": "user", "content": opening}]
        tool_log = []
        raw_text = None
        api_error = None

        for _tool_turn in range(max_tool_turns):
            response, err = _call_with_api_retries(llm_call, messages, TOOL_SPECS,
                                                     max_api_retries, api_backoff)
            if err is not None:
                api_error = f"API error: {err}"
                break

            tool_calls = response.get("tool_calls")
            if tool_calls:
                messages.append({"role": "assistant", "tool_calls": tool_calls})
                for call in tool_calls:
                    result = _execute_tool(call["name"], call.get("arguments"), ctx)
                    tool_log.append({"name": call["name"], "arguments": call.get("arguments"),
                                      "result": result})
                    messages.append({"role": "tool", "name": call["name"],
                                      "tool_call_id": call.get("id", ""), "content": result})
                continue

            raw_text = response.get("text", "")
            break
        else:
            last_error = f"model made {max_tool_turns} tool calls without a final answer"

        if api_error is not None:
            last_error = api_error
            attempts.append({"n": len(attempts) + 1, "prompt": opening, "raw_response": None,
                              "outcome": "api_error", "reason": last_error, "tool_calls": tool_log})
            continue

        if raw_text is None:
            attempts.append({"n": len(attempts) + 1, "prompt": opening, "raw_response": None,
                              "outcome": "no_final_answer", "reason": last_error,
                              "tool_calls": tool_log})
            continue

        try:
            span = extract_json_span(raw_text)
            parsed = json.loads(span)
            status, normalized = validate_response(parsed, claim_a, claim_b, available_tons)
            attempts.append({"n": len(attempts) + 1, "prompt": opening, "raw_response": raw_text,
                              "outcome": "accepted", "reason": None, "tool_calls": tool_log})
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
            attempts.append({"n": len(attempts) + 1, "prompt": opening, "raw_response": raw_text,
                              "outcome": "rejected", "reason": last_error, "tool_calls": tool_log})
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
