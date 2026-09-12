#!/bin/bash
# git-bisect predicate for the recovery beat. Checks whether the resolved
# demo stream's allocation is internally consistent (allocated tons sum to
# <= available_tons; no negatives).
#
# Exit 0 = good, 1 = bad, 125 = this commit cannot be judged (git-bisect-run's
# "skip" code). The two guards below exist because a naive script exits 127
# ("command not found") at any commit predating the stream file or this very
# validator, and git-bisect-run reads 1-127-except-125 as BAD -- which makes
# bisect confidently name the commit that first added the stream file as the
# first bad commit. Never let that happen: missing file/validator is
# untestable, not bad.
#
# Run this from OUTSIDE the bisected tree (a bisect rewrites the working tree
# under this script's feet):
#   cp agents/check_allocation.sh agents/validate_allocation.py agents/stream_io.py /tmp/bisect/
#   export BISECT_VALIDATOR=/tmp/bisect/validate_allocation.py
#   git bisect start HEAD <known-good-commit>
#   git bisect run /tmp/bisect/check_allocation.sh
#   git bisect reset   # ALWAYS, before anything else runs

set -u

STREAM="streams/AK8570028649-D009-W301-2001.yaml"
VALIDATOR="${BISECT_VALIDATOR:?BISECT_VALIDATOR must point at a copy of validate_allocation.py outside the bisected tree}"

[ -f "$STREAM" ] || exit 125       # stream file not yet in this commit -> untestable
[ -f "$VALIDATOR" ] || exit 125    # validator unavailable -> untestable, never "bad"

python3 "$VALIDATOR" "$STREAM"
rc=$?
[ "$rc" -ge 2 ] && exit 125         # parse error / unresolved commit != a bad allocation
exit "$rc"
