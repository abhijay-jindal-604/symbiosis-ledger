"""The Phase 9 filmable beat: run agents/planner.py's run_plan() against a
fresh, never-claimed stream (streams/AK9999999999-F003D009-W231-2026.yaml).

Unlike demo/rerun_with_memory.py, this script does NOT reset any receiver
profile at the top -- the two-run story here is two separate invocations of
`python demo/run_planner.py`, not two calls inside one process, and the
second invocation's shorter plan only means something if it's reading the
real, persisted result of the first.

Run 1 (first ever invocation against this stream): recycler-d has zero real
receipts of either code on this stream, but ties every other candidate on
that (zero) receipt count, and wins the ranking tiebreak on its own
declared specialty ("solvent recycler" matches the F-code's implied
category) -- so it's proposed first, genuinely denied, and the run
continues to the next-ranked candidate, which has a real recorded receipt
and is accepted.

Run 2 (run this script again, same stream, same repo state): plan_stream()
now finds recycler-d's rejection already on record for this stream_id and
excludes it from the ranked list entirely -- a strictly shorter plan than
run 1's, with the excluded candidate named alongside the exact recorded
rejection date, and no snapshot re-query for it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agents"))
from planner import run_plan  # noqa: E402

STREAM_PATH = "streams/AK9999999999-F003D009-W231-2026.yaml"


def main():
    result = run_plan(STREAM_PATH)

    print(f"=== planner: {result['stream_id']} (primary code {result['primary_code']}) ===\n")

    print(f"ranked candidates ({len(result['candidates'])}):")
    for c in result["candidates"]:
        print(f"  {c['candidate']}: receipt_count={c['receipt_count']} "
              f"specificity={c['specificity']} total_tons_handled={c['total_tons_handled']}")

    if result["skipped"]:
        print(f"\nskipped, prior rejection already on record ({len(result['skipped'])}):")
        for s in result["skipped"]:
            r = s["rejection"]
            print(f"  {s['candidate']}: rejected {r['date']} -- {r['reason']}")
    else:
        print("\nskipped: none (this is the first time this stream has been planned)")

    print("\nwalk:")
    for a in result["attempts"]:
        verdict = "ACCEPTED" if a["proposed"] else "denied"
        print(f"  {a['candidate']}: {verdict} -- {a['reason']}")

    print()
    if result["no_eligible_candidate"]:
        print("NO ELIGIBLE CANDIDATE -- plan exhausted without an acceptance")
        sys.exit(1)
    print(f"accepted: {result['accepted']}")


if __name__ == "__main__":
    main()
