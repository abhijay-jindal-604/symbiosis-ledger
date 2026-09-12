"""The planner (Phase 9): decides *which* receivers to approach for a
stream, in what order, and replans on denial -- the `planning` word the
rest of this repo doesn't yet cover. orchestrate.propose() already decides
whether one named claimant should be proposed, consulting that receiver's
own memory profile first; this module sits one layer above it, discovering
and ranking every candidate receiver, then walking orchestrate.propose()
over them in order. It does not reimplement eligibility or memory -- both
stay owned by eligibility_check.py and orchestrate.py.

Ranking is deterministic and auditable, never left to a model's taste:
(1) real recorded receipts of the stream's *primary* waste code (the first
federal waste code listed on the stream, read left to right) under a
recovery-type management method: real history always outranks none;
(2) whether the candidate's own declared specialty (data/receivers.json's
role_label, matched against a small static keyword table) matches the
recovery category that primary code implies -- a tiebreak only, so a
receiver with zero real receipts can never outrank one with real receipts,
but can win a tie against another zero-receipt candidate;
(3) total tons the candidate has actually handled under any recovery-type
method, as a final tiebreak;
(4) candidate alias, alphabetically, so the order is fully deterministic
even on an exact triple tie.

A candidate with a rejection already recorded in its own profile for this
exact stream_id is excluded from the ranked list entirely (not merely
ranked last) and reported separately as "skipped" -- this is what makes a
second plan_stream() call, after a denial has been recorded, measurably
shorter than the first, without re-querying the snapshot for that candidate.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eligibility_check import RECOVERY_CATEGORIES, CODE_RE, load_receivers, load_snapshot
from orchestrate import load_profile, prior_rejection, propose
from stream_io import load_stream

# Declared specialty per receiver, read from data/receivers.json's own
# role_label field -- never inferred by a model. Used only to break ties
# among candidates that are otherwise equal on real receipt history.
SPECIALTY_KEYWORDS = [
    ("solvent", "SOLVENTS RECOVERY"),
    ("metal", "METALS RECOVERY"),
]

# Which recovery category a waste code's letter prefix typically implies,
# for the narrow set of prefixes this repo's data actually contains
# (F-listed spent solvents, D004-D011 toxicity-characteristic metals).
CODE_PREFIX_CATEGORY = {
    "F": "SOLVENTS RECOVERY",
    "D": "METALS RECOVERY",
}


def _declared_specialty(role_label):
    role_label = (role_label or "").lower()
    for keyword, category in SPECIALTY_KEYWORDS:
        if keyword in role_label:
            return category
    return "OTHER RECOVERY"


def primary_code(stream):
    """The stream's first federal waste code, left to right -- the code
    ranking scores candidates against. (Eligibility itself, via
    orchestrate.propose(), still checks the *full* set of the stream's
    codes; only ranking narrows to this one.)"""
    codes = CODE_RE.findall(stream["waste"]["federal_waste_codes"])
    return codes[0] if codes else None


def _score_candidate(alias, info, code, snapshot):
    handler_id = info["handler_id"]
    rows = [
        r for r in snapshot
        if r.get("receiver_id") == handler_id and r.get("management_category") in RECOVERY_CATEGORIES
    ]
    receipt_count = sum(
        1 for r in rows if code is not None and code in CODE_RE.findall(r.get("federal_waste_codes") or "")
    )
    implied_category = CODE_PREFIX_CATEGORY.get(code[0]) if code else None
    specificity = 1 if implied_category and _declared_specialty(info.get("role_label")) == implied_category else 0
    total_tons = sum(float(r.get("shipped_tons") or 0) for r in rows)
    return {
        "candidate": alias,
        "receiver_id": handler_id,
        "receipt_count": receipt_count,
        "specificity": specificity,
        "total_tons_handled": round(total_tons, 4),
    }


def plan_stream(stream_path, receivers=None, snapshot=None):
    """Rank every known receiver as a candidate for the stream at
    `stream_path`. Returns:
    {"stream_id", "primary_code", "candidates": [ranked score dicts],
     "skipped": [{"candidate", "rejection"}]}

    `candidates` excludes any receiver with a prior rejection already
    recorded (in its own profile file) for this exact stream_id; those are
    reported in `skipped` instead, each carrying the actual recorded
    rejection entry -- no snapshot re-query needed to explain the skip.
    """
    receivers = receivers if receivers is not None else load_receivers()
    snapshot = snapshot if snapshot is not None else load_snapshot()
    stream = load_stream(stream_path)
    stream_id = stream["stream_id"]
    code = primary_code(stream)

    candidates, skipped = [], []
    for alias, info in receivers.items():
        profile = load_profile(info["handler_id"])
        prior = prior_rejection(profile, stream_id)
        if prior is not None:
            skipped.append({"candidate": alias, "rejection": prior})
            continue
        candidates.append(_score_candidate(alias, info, code, snapshot))

    candidates.sort(key=lambda c: (
        -c["receipt_count"], -c["specificity"], -c["total_tons_handled"], c["candidate"],
    ))
    return {"stream_id": stream_id, "primary_code": code, "candidates": candidates, "skipped": skipped}


def run_plan(stream_path, receivers=None, snapshot=None, rationale_call=None):
    """Walk plan_stream()'s ranked candidate list, calling the existing
    orchestrate.propose() for each candidate in order -- eligibility and
    memory stay owned by orchestrate.py/eligibility_check.py, this only
    decides the order and when to stop. Stops at the first acceptance.

    `rationale_call(plan, attempts, accepted) -> str`, if given, is an
    optional model call for a plain-language justification of the ordering
    -- never consulted for the ordering itself, and never allowed to break
    the run: any exception it raises is caught and recorded as an
    unavailable rationale rather than propagated.

    Returns plan_stream()'s dict plus:
    {"attempts": [{"candidate", "proposed", "reason"}], "accepted": alias|None,
     "no_eligible_candidate": bool, "rationale": str|None}
    """
    receivers = receivers if receivers is not None else load_receivers()
    snapshot = snapshot if snapshot is not None else load_snapshot()
    plan = plan_stream(stream_path, receivers, snapshot)

    attempts = []
    accepted = None
    for candidate in plan["candidates"]:
        result = propose(stream_path, candidate["candidate"], receivers=receivers, snapshot=snapshot)
        attempts.append({
            "candidate": candidate["candidate"],
            "proposed": result["proposed"],
            "reason": result["reason"],
        })
        if result["proposed"]:
            accepted = candidate["candidate"]
            break

    rationale = None
    if rationale_call is not None:
        try:
            rationale = rationale_call(plan, attempts, accepted)
        except Exception as e:  # the ordering above is already final; a broken rationale call
            rationale = f"[rationale unavailable: {e}]"  # must never take the run down with it

    return {
        "stream_id": plan["stream_id"],
        "primary_code": plan["primary_code"],
        "candidates": plan["candidates"],
        "skipped": plan["skipped"],
        "attempts": attempts,
        "accepted": accepted,
        "no_eligible_candidate": accepted is None,
        "rationale": rationale,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stream", required=True)
    args = parser.parse_args()

    result = run_plan(args.stream)
    print(f"stream={result['stream_id']}  primary_code={result['primary_code']}")
    print("ranked candidates:")
    for c in result["candidates"]:
        print(f"  {c['candidate']}: receipt_count={c['receipt_count']} "
              f"specificity={c['specificity']} total_tons_handled={c['total_tons_handled']}")
    if result["skipped"]:
        print("skipped (prior rejection on record):")
        for s in result["skipped"]:
            print(f"  {s['candidate']}: rejected {s['rejection']['date']} -- {s['rejection']['reason']}")
    print("walk:")
    for a in result["attempts"]:
        print(f"  {a['candidate']}: proposed={a['proposed']}  reason={a['reason']}")
    if result["no_eligible_candidate"]:
        print("NO ELIGIBLE CANDIDATE -- plan exhausted without an acceptance")
    else:
        print(f"accepted: {result['accepted']}")
    sys.exit(0 if not result["no_eligible_candidate"] else 1)


if __name__ == "__main__":
    main()
