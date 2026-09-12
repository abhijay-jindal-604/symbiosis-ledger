"""Seeds one deliberately corrupt commit -- a resolution whose allocated
tons exceed what's actually available, simulating a misread constraint --
on a dedicated demo/bisect-history branch. Never on main: main's history is
the evidence a judge audits, and a deliberately corrupt commit sitting
there invites exactly the wrong question. Only the *setup* of this bug is
scripted; the bisect that finds it runs for real (see agents/check_allocation.sh).

Re-running this script is safe and idempotent: it always re-forks
demo/bisect-history from main's current tip before seeding, so rehearsals
stay reproducible instead of piling up bug-on-bug commits.
"""
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agents"))
from stream_io import load_stream, write_stream  # noqa: E402

BRANCH = "demo/bisect-history"
STREAM_PATH = "streams/AK8570028649-D009-W301-2001.yaml"
OVERALLOCATION = 50  # tons over available_tons -- large enough that it's not a rounding accident


def run(*args):
    subprocess.run(args, check=True)


def capture(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def main():
    starting_branch = capture("git", "rev-parse", "--abbrev-ref", "HEAD")

    run("git", "branch", "-f", BRANCH, "main")
    run("git", "checkout", BRANCH)

    stream = load_stream(STREAM_PATH)
    claims = stream.get("claims") or []
    if not claims:
        sys.exit(f"{STREAM_PATH} has no claims to corrupt -- run this after Phase 4's resolution "
                  "commit exists on main")

    target = claims[0]
    available = stream["waste"]["available_tons"]
    target["allocated_tons"] = available + OVERALLOCATION
    target["schedule"] = "SEEDED BUG (demo/seed_bad_commit.py): misread constraint, over-allocated"

    write_stream(STREAM_PATH, stream)
    run("git", "add", STREAM_PATH)
    run("git", "commit", "-m",
        f"demo: seed bad allocation for {target['claimant']} (misread constraint) -- bisect beat")

    bad_sha = capture("git", "rev-parse", "HEAD")
    good_sha = capture("git", "rev-parse", "main")

    print(f"Seeded bad commit {bad_sha} on {BRANCH} (parent {good_sha} on main is the last known-good).")
    print(f"Rehearse with:\n"
          f"  cp agents/check_allocation.sh agents/validate_allocation.py agents/stream_io.py /tmp/bisect/\n"
          f"  export BISECT_VALIDATOR=/tmp/bisect/validate_allocation.py\n"
          f"  git bisect start {bad_sha} {good_sha}\n"
          f"  git bisect run /tmp/bisect/check_allocation.sh\n"
          f"  git bisect reset")

    run("git", "checkout", starting_branch)
    print(f"Switched back to {starting_branch}.")


if __name__ == "__main__":
    main()
