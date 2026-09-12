"""Pure allocation validator. Used directly by tests and, wrapped by
check_allocation.sh, as the git-bisect-run predicate for the recovery beat.

Exit-code discipline is the whole reliability of the bisect beat (see
CONTEXT-DUMP §7): 0 = good allocation, 1 = a genuine arithmetic violation
(bad), >=2 = this commit cannot be judged at all (missing file, unresolved
stream, parse error) -- check_allocation.sh maps >=2 to bisect's 125
("skip, untestable"), which must never be conflated with "bad".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stream_io import load_stream

TOLERANCE = 0.01


class UnevaluableError(Exception):
    """The commit's state can't be judged good/bad at all (untestable)."""


def validate(stream):
    """Return (ok, message) for a resolved stream, or raise UnevaluableError
    if there's nothing to judge yet (unresolved, or a required field is
    missing -- never mistake either for a bad allocation)."""
    if not stream.get("resolution"):
        raise UnevaluableError("resolution is null -- stream not yet resolved, nothing to validate")

    available = (stream.get("waste") or {}).get("available_tons")
    if available is None:
        raise UnevaluableError("waste.available_tons missing")

    claims = stream.get("claims") or []
    if not claims:
        raise UnevaluableError("resolution present but claims is empty")

    total = 0.0
    for claim in claims:
        tons = claim.get("allocated_tons")
        if tons is None:
            raise UnevaluableError(f"claim for {claim.get('claimant')} has no allocated_tons")
        if tons < 0:
            return False, f"negative allocation ({tons}) for {claim.get('claimant')}"
        total += tons

    if total > available + TOLERANCE:
        return False, f"allocated total {total} exceeds available {available}"
    return True, f"allocated total {total} within available {available}"


def main():
    if len(sys.argv) != 2:
        print("usage: validate_allocation.py <stream_path>", file=sys.stderr)
        sys.exit(2)
    path = sys.argv[1]

    try:
        stream = load_stream(path)
    except Exception as e:
        print(f"UNTESTABLE: cannot load {path}: {e}")
        sys.exit(2)

    try:
        ok, msg = validate(stream)
    except UnevaluableError as e:
        print(f"UNTESTABLE: {e}")
        sys.exit(2)

    if ok:
        print(f"GOOD: {msg}")
        sys.exit(0)
    print(f"BAD: {msg}")
    sys.exit(1)


if __name__ == "__main__":
    main()
