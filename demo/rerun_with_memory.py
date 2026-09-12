"""The §8 memory beat, on camera: run recycler-d's ineligible-receiver
scenario against the demo stream twice through the orchestration layer
(agents/orchestrate.py) -- not the CI eligibility check itself, which is
stateless per-PR by design.

Run 1: recycler-d has no recorded recovery-type receipt of this waste code
-> denied, and the rejection is logged to its profile file
(receivers/profiles/<receiver_id>.json).

Run 2: same input, same script -- orchestrate.py reads that profile first
and skips re-proposing recycler-d without re-querying the snapshot at all.
Same input twice, different/shorter behavior, and the printed line names
exactly which prior record caused the skip.

Resets recycler-d's profile at the top so this script gives the same
two-run story on every rehearsal; that reset is demo staging, the two
propose() calls are the real mechanism being demonstrated.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agents"))
from orchestrate import load_receivers, profile_path, propose  # noqa: E402

STREAM_PATH = "streams/AK8570028649-D009-W301-2001.yaml"
CLAIMANT = "recycler-d"


def main():
    receivers = load_receivers()
    handler_id = receivers[CLAIMANT]["handler_id"]
    path = profile_path(handler_id)

    if os.path.exists(path):
        os.remove(path)
        print(f"(demo staging: cleared {path} so this rehearsal starts with no memory)\n")

    print(f"=== Run 1: orchestrate.propose({CLAIMANT!r}) against {STREAM_PATH} ===")
    result1 = propose(STREAM_PATH, CLAIMANT)
    print(f"proposed={result1['proposed']}  reason={result1['reason']}\n")

    print(f"=== Run 2: same claimant, same stream, run again ===")
    result2 = propose(STREAM_PATH, CLAIMANT)
    print(f"proposed={result2['proposed']}  reason={result2['reason']}\n")

    if result1["proposed"]:
        sys.exit(f"expected run 1 to deny {CLAIMANT} -- check data/receivers.json / the snapshot")
    if not result2["reason"].startswith("skipping"):
        sys.exit(f"expected run 2 to skip {CLAIMANT} from memory -- check {path}")

    print(f"Confirmed: run 2 skipped re-proposing {CLAIMANT}, reading its own prior rejection "
          f"from {path} instead of re-querying the snapshot.")


if __name__ == "__main__":
    main()
