"""Required CI check ('the verifier', honestly not the reasoning): for each
claimant that appears under claims: in a stream file changed by this PR,
look up their real EPA handler_id and check the committed snapshot for a
receipt of this stream's waste code under a recovery-type management
category. Exit 0 if every claimant is eligible, 1 if any is denied.

No diff parsing: reads whichever stream file(s) under streams/ changed
relative to main, and checks whichever claimant(s) appear in claims: at HEAD.
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stream_io import load_stream

RECEIVERS_PATH = "data/receivers.json"
SNAPSHOT_PATH = "data/br_reporting_snapshot.json"
RECOVERY_CATEGORIES = {"METALS RECOVERY", "OTHER RECOVERY", "SOLVENTS RECOVERY"}
CODE_RE = re.compile(r"[A-Z]\d{3}")


def changed_stream_files():
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "origin/main...HEAD", "--", "streams/"],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        out = subprocess.run(
            ["git", "diff", "--name-only", "main...HEAD", "--", "streams/"],
            capture_output=True, text=True, check=True,
        ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def load_receivers():
    with open(RECEIVERS_PATH) as f:
        return json.load(f)


def load_snapshot():
    with open(SNAPSHOT_PATH) as f:
        return json.load(f)["rows"]


def check_eligibility(claimant, receivers, snapshot, waste_codes):
    info = receivers.get(claimant)
    if info is None:
        return False, f"ELIGIBILITY DENIED — unknown claimant '{claimant}', no entry in {RECEIVERS_PATH}"
    handler_id = info["handler_id"]
    matches = []
    for row in snapshot:
        if row.get("receiver_id") != handler_id:
            continue
        if row.get("management_category") not in RECOVERY_CATEGORIES:
            continue
        row_codes = set(CODE_RE.findall(row.get("federal_waste_codes") or ""))
        if row_codes & waste_codes:
            matches.append(row)
    if matches:
        codes_str = ",".join(sorted(waste_codes))
        category = matches[0]["management_category"]
        return True, (
            f"ELIGIBLE — receiver {handler_id} has {len(matches)} recorded receipt(s) "
            f"of waste code {codes_str} under a recovery-type method ({category}), by waste code"
        )
    codes_str = ",".join(sorted(waste_codes))
    years = sorted({r["report_cycle"] for r in snapshot if r.get("receiver_id") == handler_id}) or ["n/a"]
    return False, (
        f"ELIGIBILITY DENIED — receiver {handler_id} has 0 recorded receipts of waste code "
        f"{codes_str} under a recovery-type method (report cycle {years[0]})"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--claimant", help="check a single claimant against every stream (local/manual use)")
    parser.add_argument("--stream", help="stream file path, used with --claimant")
    args = parser.parse_args()

    receivers = load_receivers()
    snapshot = load_snapshot()

    if args.claimant:
        stream_path = args.stream or _find_stream_for_claimant(args.claimant)
        if stream_path is None:
            print(f"No stream file found with claimant '{args.claimant}'")
            sys.exit(1)
        stream = load_stream(stream_path)
        waste_codes = set(CODE_RE.findall(stream["waste"]["federal_waste_codes"]))
        ok, msg = check_eligibility(args.claimant, receivers, snapshot, waste_codes)
        print(msg)
        sys.exit(0 if ok else 1)

    changed = changed_stream_files()
    if not changed:
        print("NO STREAM CLAIMS IN THIS PR — nothing to verify")
        sys.exit(0)

    overall_ok = True
    for path in changed:
        try:
            stream = load_stream(path)
        except FileNotFoundError:
            continue  # file deleted in this PR
        waste_codes = set(CODE_RE.findall(stream["waste"]["federal_waste_codes"]))
        claimants = [c["claimant"] for c in (stream.get("claims") or [])]
        if not claimants:
            print(f"{path}: no claims present, nothing to verify")
            continue
        for claimant in claimants:
            ok, msg = check_eligibility(claimant, receivers, snapshot, waste_codes)
            print(f"{path} [{claimant}]: {msg}")
            overall_ok = overall_ok and ok

    sys.exit(0 if overall_ok else 1)


def _find_stream_for_claimant(claimant):
    """Find which stream file to check `claimant` against, for the manual
    `--claimant` CLI path. Prefers a stream where this claimant has actually
    filed a claims: entry, but falls back to the one stream file present
    when there's exactly one and no claim matched -- otherwise a claimant
    whose claim was deliberately never merged (e.g. an ineligible receiver's
    denial-evidence PR, left open on its own branch rather than landing on
    main) can never be checked from main at all, breaking the single most
    basic command a reader would try."""
    import glob
    paths = glob.glob("streams/*.yaml")
    for path in paths:
        stream = load_stream(path)
        if any(c["claimant"] == claimant for c in (stream.get("claims") or [])):
            return path
    if len(paths) == 1:
        return paths[0]
    return None


if __name__ == "__main__":
    main()
