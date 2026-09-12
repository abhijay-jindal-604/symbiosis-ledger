"""Thin Gemini wrapper providing the llm_call(messages, tools) -> dict
signature that negotiation_agent.negotiate() expects. negotiation_agent.py
stays provider-agnostic and untested against any real API; this is the only
file that imports the Gemini SDK, and the only place that knows Gemini's
function-calling shape.

Requires GEMINI_API_KEY in the environment (loaded from a gitignored .env
locally; never wired into CI, which reads the committed snapshot only).

Manual (non-automatic) function calling, per the google-genai SDK: tools are
declared via types.FunctionDeclaration + types.Tool, automatic execution is
disabled so this module controls the loop, and each tool round-trip is sent
back to the model as its own turn (FunctionDeclaration/Tool/Part.from_function_call/
Part.from_function_response, confirmed against the current python-genai docs).

Gemini 3.5 requires a `thought_signature` (an opaque, model-issued bytes
value) to be echoed back on a reconstructed function-call turn -- confirmed
by a real 400 INVALID_ARGUMENT during this project's own second live run
("Function call is missing a thought_signature in functionCall parts"),
not found in any doc example, which reconstructs the follow-up turn from
`response.candidates[0].content` directly rather than from name+args. This
module can't do that (negotiation_agent.py owns history across an
in-between tool-execution step it doesn't get to see), so instead the
signature is threaded through the generic tool_call dict as an opaque
extra field the rest of the codebase never inspects, and reattached here
on reconstruction.
"""
import base64
import json
import os
from datetime import date

MODEL_NAME = os.environ.get("NEGOTIATION_MODEL", "gemini-3.5-flash")


def _to_gemini_tools(types, tool_specs):
    if not tool_specs:
        return None
    declarations = [
        types.FunctionDeclaration(
            name=spec["name"],
            description=spec["description"],
            parameters_json_schema=spec["parameters"],
        )
        for spec in tool_specs
    ]
    return [types.Tool(function_declarations=declarations)]


def _to_gemini_contents(types, messages):
    contents = []
    for msg in messages:
        role = msg["role"]
        if role == "user":
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=msg["content"])]))
        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                parts = []
                for c in tool_calls:
                    part = types.Part.from_function_call(name=c["name"], args=c.get("arguments") or {})
                    signature = c.get("_thought_signature")
                    if signature is not None:
                        part.thought_signature = signature
                    parts.append(part)
                contents.append(types.Content(role="model", parts=parts))
            else:
                contents.append(types.Content(role="model", parts=[
                    types.Part.from_text(text=msg.get("content", ""))
                ]))
        elif role == "tool":
            # The python-genai docs' own example wraps a function response in
            # Content(role="tool", ...), and gemini-3.5-flash accepts that --
            # but gemini-3.6-flash/3.7-flash/3.8-flash all reject it outright
            # ("Role 'tool' is not supported"), confirmed live while adding a
            # second negotiation protocol and needing a model off 3.5-flash's
            # exhausted free-tier daily quota. "user" is in every version's
            # own stated list of valid roles, so use that instead.
            contents.append(types.Content(role="user", parts=[
                types.Part.from_function_response(name=msg["name"], response=msg["content"])
            ]))
        else:
            raise ValueError(f"unknown message role {role!r}")
    return contents


def _function_call_parts(response):
    """Yields (FunctionCall, thought_signature) pairs. thought_signature
    lives on the Part, not on FunctionCall itself, so this walks
    response.candidates[0].content.parts directly rather than using the
    flattened response.function_calls property, which drops it."""
    if not response.candidates or not response.candidates[0].content:
        return
    for part in response.candidates[0].content.parts or []:
        if part.function_call is not None:
            yield part.function_call, part.thought_signature


def get_llm_call():
    """Returns an llm_call(messages, tools=None) -> dict closure backed by the
    Gemini API. Raises RuntimeError immediately if GEMINI_API_KEY is unset,
    rather than failing confusingly on first use."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    from google import genai
    from google.genai import types

    os.environ.setdefault("NEGOTIATION_MODEL", MODEL_NAME)
    client = genai.Client(api_key=api_key)

    def llm_call(messages, tools=None):
        contents = _to_gemini_contents(types, messages)
        gemini_tools = _to_gemini_tools(types, tools)

        config_kwargs = dict(
            temperature=0,
            max_output_tokens=1024,
        )
        # "-lite" models (confirmed live on gemini-3.5-flash-lite, added to
        # dodge another model's exhausted free-tier daily quota) reject
        # thinking_config outright with a bare 400 INVALID_ARGUMENT and no
        # further detail -- they apparently have no thinking mode to budget
        # at all, unlike the full flash models this was written against.
        if "lite" not in MODEL_NAME:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        if gemini_tools:
            config_kwargs["tools"] = gemini_tools
            config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
                disable=True
            )

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )

        tool_calls = [
            {
                "id": fc.id or f"{fc.name}-{i}",
                "name": fc.name,
                "arguments": dict(fc.args or {}),
                "_thought_signature": signature,
            }
            for i, (fc, signature) in enumerate(_function_call_parts(response))
        ]
        if tool_calls:
            return {"tool_calls": tool_calls}
        return {"text": response.text or ""}

    return llm_call


# --- demo-path caching (Phase 14) -----------------------------------------
#
# This build exhausted two separate Gemini free-tier daily quotas and hit
# the 5-requests/minute rate limit during development; a quota exhaustion
# mid-recording costs a take. get_cached_llm_call() wraps the real llm_call
# with an on-disk, ordered-by-call-index cache: the first (live) run against
# a given cache_path records every request/response pair, and any later run
# -- including one with no GEMINI_API_KEY and no network at all -- replays
# them in the same order. A replayed call is always labeled on stdout, per
# the addendum's still-binding rule: if we replay, we say "replay",
# unprompted. The live path stays the default whenever a key is present and
# the call succeeds; the cache is a fallback, never the demo itself.

def _encode_bytes_for_json(obj):
    """Gemini's thought_signature (see the module docstring) is raw bytes,
    which json.dump rejects outright -- confirmed live, the first time this
    cache was populated for real. Recursively replaces any bytes value with
    a tagged base64 string so the whole response tree stays JSON-safe."""
    if isinstance(obj, bytes):
        return {"__bytes_b64__": base64.b64encode(obj).decode("ascii")}
    if isinstance(obj, dict):
        return {k: _encode_bytes_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_encode_bytes_for_json(v) for v in obj]
    return obj


def _decode_bytes_from_json(obj):
    if isinstance(obj, dict):
        if set(obj.keys()) == {"__bytes_b64__"}:
            return base64.b64decode(obj["__bytes_b64__"])
        return {k: _decode_bytes_from_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode_bytes_from_json(v) for v in obj]
    return obj


def _load_cache(cache_path):
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return _decode_bytes_from_json(json.load(f))
    return {"verified_date": None, "responses": []}


def _save_cache(cache_path, cache):
    # Written atomically (temp file + os.replace): this is called after every
    # single live call within a multi-call negotiation, so a process killed
    # mid-write (e.g. a timeout during rehearsal) must not corrupt whatever
    # calls were already safely cached.
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    tmp_path = f"{cache_path}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(_encode_bytes_for_json(cache), f, indent=2)
    os.replace(tmp_path, cache_path)


def get_cached_llm_call(cache_path):
    """Returns an llm_call(messages, tools=None) -> dict closure identical in
    shape to get_llm_call()'s, backed by a cache file at cache_path.

    Call order within a run is deterministic (temperature=0, same prompts),
    so calls are replayed strictly by position: the Nth call this run reads
    the Nth cached response. If GEMINI_API_KEY is set, each call is attempted
    live first and the cache is updated with the fresh response; if the key
    is unset, or the live call raises, the cached response for that position
    is used instead (and printed as such). Only raises if neither a live key
    nor a cached response is available for that position.
    """
    cache = _load_cache(cache_path)
    state = {"real_call": None}
    call_index = {"n": 0}

    def llm_call(messages, tools=None):
        i = call_index["n"]
        call_index["n"] += 1
        responses = cache["responses"]
        api_key = os.environ.get("GEMINI_API_KEY")

        if api_key:
            if state["real_call"] is None:
                state["real_call"] = get_llm_call()
            # The live call and the cache write are kept in separate
            # try/except scopes on purpose: only a failure of the *live
            # call itself* should fall back to a cached response labeled as
            # such. A bug in the write path must surface as a real crash,
            # never get silently swallowed into a false "cached" label on a
            # response that was, in fact, live.
            try:
                response = state["real_call"](messages, tools)
            except Exception as e:
                if i < len(responses):
                    print(f"[cached response, live-verified {cache['verified_date']}] "
                          f"(live call failed: {e})")
                    return responses[i]
                raise
            if i < len(responses):
                responses[i] = response
            else:
                responses.append(response)
            cache["verified_date"] = date.today().isoformat()
            _save_cache(cache_path, cache)
            return response

        if i >= len(responses):
            raise RuntimeError(
                f"GEMINI_API_KEY is not set and call #{i} has no cached response in "
                f"{cache_path}. Run once with a live key to populate the cache."
            )
        print(f"[cached response, live-verified {cache['verified_date']}]")
        return responses[i]

    return llm_call
