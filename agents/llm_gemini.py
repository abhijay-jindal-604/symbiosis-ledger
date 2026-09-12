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
                parts = [types.Part.from_function_call(name=c["name"], args=c.get("arguments") or {})
                         for c in tool_calls]
                contents.append(types.Content(role="model", parts=parts))
            else:
                contents.append(types.Content(role="model", parts=[
                    types.Part.from_text(text=msg.get("content", ""))
                ]))
        elif role == "tool":
            contents.append(types.Content(role="tool", parts=[
                types.Part.from_function_response(name=msg["name"], response=msg["content"])
            ]))
        else:
            raise ValueError(f"unknown message role {role!r}")
    return contents


def _function_call_name(fc):
    return fc.name


def _function_call_args(fc):
    # The python-genai docs show two slightly different attribute paths for
    # a returned function call's arguments across SDK versions/snippets
    # (fc.args directly, vs. fc.function_call.args); handle both defensively
    # rather than betting on one and breaking silently on the other.
    args = getattr(fc, "args", None)
    if args is None:
        inner = getattr(fc, "function_call", None)
        args = getattr(inner, "args", None) if inner is not None else None
    return dict(args or {})


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
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
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

        function_calls = response.function_calls
        if function_calls:
            return {"tool_calls": [
                {
                    "id": getattr(fc, "id", None) or f"{_function_call_name(fc)}-{i}",
                    "name": _function_call_name(fc),
                    "arguments": _function_call_args(fc),
                }
                for i, fc in enumerate(function_calls)
            ]}
        return {"text": response.text or ""}

    return llm_call
