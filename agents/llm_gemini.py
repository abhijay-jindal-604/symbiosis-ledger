"""Thin Gemini wrapper providing the llm_call(prompt) -> str signature that
negotiation_agent.negotiate() expects. negotiation_agent.py stays
provider-agnostic and untested against any real API; this is the only file
that imports the Gemini SDK.

Requires GEMINI_API_KEY in the environment (loaded from a gitignored .env
locally; never wired into CI, which reads the committed snapshot only).
"""
import os

MODEL_NAME = os.environ.get("NEGOTIATION_MODEL", "gemini-flash-latest")


def get_llm_call():
    """Returns an llm_call(prompt) -> str closure backed by the Gemini API.
    Raises RuntimeError immediately if GEMINI_API_KEY is unset, rather than
    failing confusingly on first use."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    def llm_call(prompt: str) -> str:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=512,
            ),
        )
        return response.text

    return llm_call
