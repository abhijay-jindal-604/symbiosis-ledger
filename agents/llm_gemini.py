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
import os

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
