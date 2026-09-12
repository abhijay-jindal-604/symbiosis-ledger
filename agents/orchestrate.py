"""The memory-aware caller (CONTEXT-DUMP §8): decides *who to propose* for
a stream, consulting each receiver's own profile file first. Negotiation
resolves *how to split* once both sides are known-proposable, and stays a
pure function of its inputs (agents/negotiation_agent.py) so it can be
unit-tested without touching git or the filesystem -- this module is the
one that reads/writes receivers/profiles/**, not that one.

Profile writes are append-only and idempotent: re-running propose() for a
claimant/stream pair that's already recorded must not duplicate the entry,
or a second demo run shows a visibly doubled file instead of a clean skip.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eligibility_check import RECOVERY_CATEGORIES  # noqa: F401  (re-exported for callers/tests)
from eligibility_check import check_eligibility, load_receivers, load_snapshot
from stream_io import load_stream

PROFILES_DIR = "receivers/profiles"
CODE_RE = re.compile(r"[A-Z]\d{3}")


def profile_path(receiver_id):
    return os.path.join(PROFILES_DIR, f"{receiver_id}.json")


def load_profile(receiver_id):
    path = profile_path(receiver_id)
    if not os.path.exists(path):
        return {"receiver_id": receiver_id, "accepted_streams": [], "rejected_claims": []}
    with open(path) as f:
        return json.load(f)


def save_profile(profile):
    os.makedirs(PROFILES_DIR, exist_ok=True)
    with open(profile_path(profile["receiver_id"]), "w") as f:
        json.dump(profile, f, indent=2)
        f.write("\n")


def prior_rejection(profile, stream_id):
    for entry in profile.get("rejected_claims", []):
        if entry.get("stream_id") == stream_id:
            return entry
    return None


def record_acceptance(profile, stream_id):
    """Idempotent: a stream already recorded as accepted is not duplicated."""
    accepted = profile.setdefault("accepted_streams", [])
    if stream_id not in accepted:
        accepted.append(stream_id)


def record_rejection(profile, stream_id, reason, date=None):
    """Idempotent: a stream already recorded as rejected is not duplicated,
    even if called again with a different reason/date."""
    if prior_rejection(profile, stream_id) is not None:
        return
    profile.setdefault("rejected_claims", []).append({
        "stream_id": stream_id,
        "reason": reason,
        "date": date or datetime.now(timezone.utc).isoformat(),
    })


def propose(stream_path, claimant, receivers=None, snapshot=None):
    """Decide whether `claimant` should be proposed for the stream at
    `stream_path`, consulting that receiver's memory profile before ever
    touching the eligibility snapshot again. Returns a dict:
    {"proposed": bool, "reason": str, "profile": dict}.

    This does not call the negotiation agent -- orchestrate only decides who
    is even in play; negotiation (a separate, pure function) decides the
    split once two proposable claimants are known.
    """
    receivers = receivers if receivers is not None else load_receivers()
    stream = load_stream(stream_path)
    stream_id = stream["stream_id"]

    info = receivers.get(claimant)
    if info is None:
        return {"proposed": False, "reason": f"unknown claimant '{claimant}'", "profile": None}
    receiver_id = info["handler_id"]
    profile = load_profile(receiver_id)

    prior = prior_rejection(profile, stream_id)
    if prior is not None:
        reason = f"skipping {claimant} — prior rejection recorded {prior['date']}: {prior['reason']}"
        print(reason)
        return {"proposed": False, "reason": reason, "profile": profile}

    snapshot = snapshot if snapshot is not None else load_snapshot()
    waste_codes = set(CODE_RE.findall(stream["waste"]["federal_waste_codes"]))
    ok, msg = check_eligibility(claimant, receivers, snapshot, waste_codes)

    if ok:
        record_acceptance(profile, stream_id)
    else:
        record_rejection(profile, stream_id, msg)
    save_profile(profile)
    return {"proposed": ok, "reason": msg, "profile": profile}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claimant", required=True)
    parser.add_argument("--stream", required=True)
    args = parser.parse_args()

    result = propose(args.stream, args.claimant)
    print(f"proposed={result['proposed']}  reason={result['reason']}")
    sys.exit(0 if result["proposed"] else 1)


if __name__ == "__main__":
    main()
