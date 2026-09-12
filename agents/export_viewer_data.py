"""Phase 10 build step: read every committed artifact the web viewer needs
and write a single web/data.json. This is a read-only export -- it must
never call orchestrate.propose() or anything else that writes a receiver
profile, since running the exporter (e.g. to preview the page) must not
change repo state. planner.plan_stream() is safe for exactly that reason:
it ranks candidates without proposing to any of them.

No new source of truth: every field in the output traces to one of
streams/*.yaml, data/receivers.json, receivers/profiles/*.json, or
logs/negotiation/*.json. All YAML reads go through the existing canonical
loader in agents/stream_io.py.
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eligibility_check import CODE_RE, check_eligibility, load_receivers, load_snapshot
from orchestrate import load_profile
from planner import plan_stream
from stream_io import load_stream

STREAMS_GLOB = "streams/*.yaml"
OUT_PATH = "web/data.json"


def _claim_with_eligibility(claim, receivers, snapshot, waste_codes):
    ok, msg = check_eligibility(claim["claimant"], receivers, snapshot, waste_codes)
    out = dict(claim)
    out["eligible"] = ok
    out["eligibility_verdict"] = msg
    return out


def _negotiation_log(resolution):
    if not resolution or not resolution.get("log"):
        return None
    log_path = resolution["log"]
    if not os.path.exists(log_path):
        return None
    with open(log_path) as f:
        return json.load(f)


def export_stream(stream_path, receivers, snapshot):
    stream = load_stream(stream_path)
    waste_codes = set(CODE_RE.findall(stream["waste"]["federal_waste_codes"]))
    claims = [
        _claim_with_eligibility(c, receivers, snapshot, waste_codes)
        for c in (stream.get("claims") or [])
    ]
    plan = plan_stream(stream_path, receivers=receivers, snapshot=snapshot)
    return {
        "stream_id": stream["stream_id"],
        "generator": stream["generator"],
        "waste": stream["waste"],
        "current_disposition": stream.get("current_disposition"),
        "status": stream["status"],
        "claims": claims,
        "resolution": stream.get("resolution"),
        "negotiation_log": _negotiation_log(stream.get("resolution")),
        "plan": plan,
        "source_file": stream_path,
    }


def export_receivers(receivers):
    out = {}
    for alias, info in receivers.items():
        profile = load_profile(info["handler_id"])
        out[alias] = {
            "handler_id": info["handler_id"],
            "display_name": info.get("display_name"),
            "role_label": info.get("role_label"),
            "expected_eligibility": info.get("expected_eligibility"),
            "accepted_streams": profile.get("accepted_streams", []),
            "rejected_claims": profile.get("rejected_claims", []),
        }
    return out


def build_data():
    receivers = load_receivers()
    snapshot = load_snapshot()
    stream_paths = sorted(glob.glob(STREAMS_GLOB))
    return {
        "streams": [export_stream(p, receivers, snapshot) for p in stream_paths],
        "receivers": export_receivers(receivers),
        "disclaimer": (
            "This page renders committed repo state as of export time. "
            "It is not a live system and transmits nothing."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=OUT_PATH)
    args = parser.parse_args()

    data = build_data()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(data, f, indent=2, default=str)
        f.write("\n")
    print(f"wrote {args.out}: {len(data['streams'])} stream(s), {len(data['receivers'])} receiver(s)")


if __name__ == "__main__":
    main()
