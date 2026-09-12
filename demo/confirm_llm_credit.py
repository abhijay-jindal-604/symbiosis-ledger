"""Phase 0 task 5: one real throwaway call to confirm the provisioned
GEMINI_API_KEY has credit and works, before Phase 4 needs it for real.
Not part of the demo narration — just a setup check.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agents"))

if os.path.exists(".env"):
    for line in open(".env"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)

from llm_gemini import get_llm_call  # noqa: E402

if __name__ == "__main__":
    llm_call = get_llm_call()
    reply = llm_call("Reply with exactly one word: OK")
    print(f"model={os.environ.get('NEGOTIATION_MODEL', 'gemini-2.5-flash')}")
    print(f"raw reply: {reply!r}")
    print("CREDIT CONFIRMED" if reply.strip() else "EMPTY RESPONSE")
