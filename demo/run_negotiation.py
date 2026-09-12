"""Runs the real merge-resolution flow from CONTEXT-DUMP.md §7 "How the
resolution actually lands" against the two open claim branches.

Does NOT push or touch GitHub itself — it leaves the resolved commit sitting
on claim/kiln-b, ready for `git push origin claim/kiln-b`, CI re-run,
CODEOWNERS approval, and merge via the UI (all separate, deliberate steps
so nothing here bypasses the on-camera gates).

Usage: run from the repo root, on a clean tree, with GEMINI_API_KEY set
(directly or via a gitignored .env in the repo root).
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "agents"))

DEFAULT_STREAM_PATH = "streams/AK8570028649-D009-W301-2001.yaml"
DEFAULT_BASE_BRANCH = "claim/kiln-b"
DEFAULT_OTHER_BRANCH = "claim/wwtp-c"


def _load_env_file():
    env_path = os.path.join(REPO_ROOT, ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)


def run(cmd, **kwargs):
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=REPO_ROOT, check=True, text=True,
                           capture_output=True, **kwargs)


def git_show(ref, path):
    out = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=REPO_ROOT,
                          check=True, text=True, capture_output=True).stdout
    return out


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
    parser.add_argument("--stream", default=DEFAULT_STREAM_PATH,
                         help="stream file path, as it appears on both claim branches")
    parser.add_argument("--base-branch", default=DEFAULT_BASE_BRANCH,
                         help="the claim branch that will carry the resolution commit and PR")
    parser.add_argument("--other-branch", default=DEFAULT_OTHER_BRANCH,
                         help="the other claim branch merged into --base-branch to produce the conflict")
    args = parser.parse_args()
    stream_path, base_branch, other_branch = args.stream, args.base_branch, args.other_branch

    _load_env_file()
    from stream_io import load_stream_str, write_stream
    from negotiation_agent import negotiate
    from llm_gemini import get_llm_call
    from eligibility_check import load_receivers, load_snapshot, CODE_RE

    status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                             check=True, text=True, capture_output=True).stdout
    if status.strip():
        print("Working tree is not clean; commit or stash first.", file=sys.stderr)
        sys.exit(1)

    run(["git", "fetch", "origin"])
    run(["git", "checkout", base_branch])
    run(["git", "pull", "--ff-only", "origin", base_branch])

    kiln_b_yaml = git_show(f"origin/{base_branch}", stream_path)
    wwtp_c_yaml = git_show(f"origin/{other_branch}", stream_path)
    stream_a = load_stream_str(kiln_b_yaml)
    stream_b = load_stream_str(wwtp_c_yaml)

    claim_a = stream_a["claims"][0]
    claim_b = stream_b["claims"][0]
    print(f"Claimant A ({claim_a['claimant']}): {claim_a.get('disclosed_constraint')!r}, "
          f"requested {claim_a['requested_tons']}")
    print(f"Claimant B ({claim_b['claimant']}): {claim_b.get('disclosed_constraint')!r}, "
          f"requested {claim_b['requested_tons']}")

    merge = subprocess.run(["git", "merge", "--no-commit", "--no-ff", f"origin/{other_branch}"],
                            cwd=REPO_ROOT, text=True, capture_output=True)
    print(merge.stdout)
    print(merge.stderr)
    if merge.returncode == 0:
        print("WARNING: merge did not conflict as expected. Aborting run — investigate.",
              file=sys.stderr)
        subprocess.run(["git", "merge", "--abort"], cwd=REPO_ROOT)
        sys.exit(1)

    stream_id = stream_a["stream_id"]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = f"logs/negotiation/{stream_id}-{ts}.json"

    receivers = load_receivers()
    snapshot = load_snapshot()
    waste_codes = set(CODE_RE.findall(stream_a["waste"]["federal_waste_codes"]))

    llm_call = get_llm_call()
    result = negotiate(
        stream_a, claim_a, claim_b, llm_call,
        lookup_receipt_history=_make_lookup_receipt_history(receivers, snapshot, waste_codes),
        get_receiver_profile=_make_get_receiver_profile(receivers),
        log_path=os.path.join(REPO_ROOT, log_path),
    )
    print("negotiate() result:", result)

    resolved = dict(stream_a)
    resolved["status"] = result["status"]
    resolved["claims"] = []
    alloc_by_name = {a["claimant"]: a for a in result.get("allocation", [])}
    for claim in (claim_a, claim_b):
        name = claim["claimant"]
        entry = dict(claim)
        entry.pop("requested_tons", None)
        alloc = alloc_by_name.get(name)
        if alloc:
            entry["allocated_tons"] = alloc["tons"]
            entry["schedule"] = alloc.get("schedule", "")
        resolved["claims"].append(entry)
    resolved["resolution"] = {
        "method": result["method"],
        "resolved_by": result["resolved_by"],
        "feasible": result["feasible"],
        "explanation": result["explanation"],
        "log": log_path,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    write_stream(os.path.join(REPO_ROOT, stream_path), resolved)

    run(["git", "add", stream_path, log_path])
    run(["git", "commit", "-m",
         f"Resolve {stream_id} conflict: {result['method'] or result['status']}\n\n"
         f"Negotiation agent read both branches' disclosed constraints and computed a "
         f"split. See {log_path} for the verbatim prompt and raw model response."])

    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
                          text=True, capture_output=True).stdout.strip()
    print(f"\nResolution commit: {sha}")
    print(f"Now on branch {base_branch}. Next steps (not automated by this script):")
    print(f"  git push origin {base_branch}")
    print(f"  # wait for CI to go green, approve as the CODEOWNERS identity, merge via UI")
    print(f"  # then close the {other_branch} PR pointing at {sha}")


if __name__ == "__main__":
    main()
