"""Runs the same real disclosed constraints through both negotiation
protocols side by side, against the real Gemini API:

  1. negotiate()       -- one call sees both claimants' constraints at once.
  2. negotiate_blind()  -- two independent calls, neither sees the other
                            claimant's name, request, or constraint.

Read-only with respect to git: this does NOT touch streams/*.yaml or commit
anything. Those files already carry the real, CODEOWNERS-approved
negotiate() resolutions from the actual claim/merge flow -- that audit
trail is not something a comparison run should ever rewrite. Instead this
reconstructs the original pre-resolution claim text from the commits that
first introduced each claim (still reachable in git history even though the
claim branches themselves were deleted after merge) and writes both
protocols' logs under logs/negotiation-compare/ for side-by-side reading.

Usage: python demo/compare_negotiation_protocols.py [--stream-id ID]
Requires GEMINI_API_KEY (directly or via a gitignored .env in the repo root).
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "agents"))

# (stream file, commit that first introduced claim A, commit for claim B)
STREAMS = {
    "AK8570028649-D009-W301-2001": (
        "streams/AK8570028649-D009-W301-2001.yaml",
        "origin/claim/kiln-b", "origin/claim/wwtp-c",
    ),
    "ALD000622464-D009-W403-2009": (
        "streams/ALD000622464-D009-W403-2009.yaml",
        "2370fc1", "7d23375",
    ),
}


def _load_env_file():
    env_path = os.path.join(REPO_ROOT, ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)


def git_show(ref, path):
    return subprocess.run(["git", "show", f"{ref}:{path}"], cwd=REPO_ROOT,
                           check=True, text=True, capture_output=True).stdout


def _make_lookup_receipt_history(receivers, snapshot, waste_codes):
    from eligibility_check import check_eligibility

    def lookup_receipt_history(claimant):
        ok, message = check_eligibility(claimant, receivers, snapshot, waste_codes)
        return {"eligible": ok, "message": message}

    return lookup_receipt_history


def _make_get_receiver_profile(receivers):
    from orchestrate import load_profile

    def get_receiver_profile(claimant):
        info = receivers.get(claimant)
        if info is None:
            return {"available": False, "message": f"unknown claimant '{claimant}'"}
        return load_profile(info["handler_id"])

    return get_receiver_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stream-id", choices=sorted(STREAMS), default="ALD000622464-D009-W403-2009")
    args = parser.parse_args()

    _load_env_file()
    from stream_io import load_stream_str
    from negotiation_agent import negotiate, negotiate_blind
    from llm_gemini import get_llm_call
    from eligibility_check import load_receivers, load_snapshot, CODE_RE

    stream_path, ref_a, ref_b = STREAMS[args.stream_id]
    stream_a = load_stream_str(git_show(ref_a, stream_path))
    stream_b = load_stream_str(git_show(ref_b, stream_path))
    claim_a = stream_a["claims"][0]
    claim_b = stream_b["claims"][0]

    print(f"Stream: {args.stream_id}  (available {stream_a['waste']['available_tons']} tons)")
    print(f"Claimant A ({claim_a['claimant']}): requested {claim_a['requested_tons']}, "
          f"constraint {claim_a.get('disclosed_constraint')!r}")
    print(f"Claimant B ({claim_b['claimant']}): requested {claim_b['requested_tons']}, "
          f"constraint {claim_b.get('disclosed_constraint')!r}")

    receivers = load_receivers()
    snapshot = load_snapshot()
    waste_codes = set(CODE_RE.findall(stream_a["waste"]["federal_waste_codes"]))
    lookup = _make_lookup_receipt_history(receivers, snapshot, waste_codes)
    profile = _make_get_receiver_profile(receivers)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = os.path.join(REPO_ROOT, "logs", "negotiation-compare")
    os.makedirs(out_dir, exist_ok=True)

    llm_call = get_llm_call()

    print("\n=== negotiate() -- single call, sees both sides at once ===")
    single_log = os.path.join(out_dir, f"{args.stream_id}-{ts}-single.json")
    single_result = negotiate(
        stream_a, claim_a, claim_b, llm_call,
        lookup_receipt_history=lookup, get_receiver_profile=profile,
        log_path=single_log, api_backoff=(60, 60),
    )
    print(single_result)

    print("\n=== negotiate_blind() -- two independent calls, blind to each other ===")
    blind_log = os.path.join(out_dir, f"{args.stream_id}-{ts}-blind.json")
    blind_result = negotiate_blind(
        stream_a, claim_a, claim_b, llm_call,
        lookup_receipt_history=lookup, get_receiver_profile=profile,
        log_path=blind_log, api_backoff=(60, 60),
    )
    print(blind_result)

    print(f"\nLogs written (not committed):\n  {single_log}\n  {blind_log}")
    print("\nNothing in streams/ or git history was touched by this comparison run.")


if __name__ == "__main__":
    main()
