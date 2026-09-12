"""Runs the real merge-resolution flow from CONTEXT-DUMP.md §7 "How the
resolution actually lands" against the two open claim branches.

Does NOT push or touch GitHub itself — it leaves the resolved commit sitting
on claim/kiln-b, ready for `git push origin claim/kiln-b`, CI re-run,
CODEOWNERS approval, and merge via the UI (all separate, deliberate steps
so nothing here bypasses the on-camera gates).

Usage: run from the repo root, on a clean tree, with GEMINI_API_KEY set
(directly or via a gitignored .env in the repo root).
"""
import os
import subprocess
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "agents"))

STREAM_PATH = "streams/AK8570028649-D009-W301-2001.yaml"
BASE_BRANCH = "claim/kiln-b"
OTHER_BRANCH = "claim/wwtp-c"


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


def main():
    _load_env_file()
    from stream_io import load_stream_str, write_stream
    from negotiation_agent import negotiate
    from llm_gemini import get_llm_call

    status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                             check=True, text=True, capture_output=True).stdout
    if status.strip():
        print("Working tree is not clean; commit or stash first.", file=sys.stderr)
        sys.exit(1)

    run(["git", "fetch", "origin"])
    run(["git", "checkout", BASE_BRANCH])
    run(["git", "pull", "--ff-only", "origin", BASE_BRANCH])

    kiln_b_yaml = git_show(f"origin/{BASE_BRANCH}", STREAM_PATH)
    wwtp_c_yaml = git_show(f"origin/{OTHER_BRANCH}", STREAM_PATH)
    stream_a = load_stream_str(kiln_b_yaml)
    stream_b = load_stream_str(wwtp_c_yaml)

    claim_a = stream_a["claims"][0]
    claim_b = stream_b["claims"][0]
    print(f"Claimant A ({claim_a['claimant']}): {claim_a.get('disclosed_constraint')!r}, "
          f"requested {claim_a['requested_tons']}")
    print(f"Claimant B ({claim_b['claimant']}): {claim_b.get('disclosed_constraint')!r}, "
          f"requested {claim_b['requested_tons']}")

    merge = subprocess.run(["git", "merge", "--no-commit", "--no-ff", f"origin/{OTHER_BRANCH}"],
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

    llm_call = get_llm_call()
    result = negotiate(stream_a, claim_a, claim_b, llm_call, log_path=os.path.join(REPO_ROOT, log_path))
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

    write_stream(os.path.join(REPO_ROOT, STREAM_PATH), resolved)

    run(["git", "add", STREAM_PATH, log_path])
    run(["git", "commit", "-m",
         f"Resolve {stream_id} conflict: {result['method'] or result['status']}\n\n"
         f"Negotiation agent read both branches' disclosed constraints and computed a "
         f"split. See {log_path} for the verbatim prompt and raw model response."])

    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
                          text=True, capture_output=True).stdout.strip()
    print(f"\nResolution commit: {sha}")
    print(f"Now on branch {BASE_BRANCH}. Next steps (not automated by this script):")
    print(f"  git push origin {BASE_BRANCH}")
    print(f"  # wait for CI to go green, approve as the CODEOWNERS identity, merge via UI")
    print(f"  # then close the {OTHER_BRANCH} PR pointing at {sha}")


if __name__ == "__main__":
    main()
