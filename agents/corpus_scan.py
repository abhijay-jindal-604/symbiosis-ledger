"""Phase 11 — the corpus-scale impact number.

`data/br_reporting_snapshot.json` holds 7 hand-picked rows: enough to run the
demo, not enough to claim anything about the scale of the problem. This
script pulls a real bulk sample of EPA `BR_REPORTING` (5-10k rows, not 7),
runs the **existing, unforked** eligibility rule from `eligibility_check.py`
across the whole sample, and reports how many disposal-bound, D-code-carrying
rows have at least one receiver *in the same sample* with real recovery-type
receipt history for that exact code.

Unfiltered bulk pull only — never the `handler_id` path filter, which
`demo/live_query.py` and `PROGRESS.md` both document as returning
non-matching row sets against `receiver_id`/unfiltered pulls for the same
underlying row (confirmed twice, likely replica lag on data.epa.gov).

Everything here is a sample of one table, not the whole table, and the
gate this counts is "shares a receiver's exact recovery code" — necessary,
not sufficient, for "will be diverted". See the printed report's `limits`
and the README for the honest reading of the number.
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eligibility_check import RECOVERY_CATEGORIES, CODE_RE

CORPUS_DIR = "data/corpus"
META_PATH = os.path.join(CORPUS_DIR, "meta.json")
SUMMARY_PATH = "data/corpus_summary.json"
BASE_URL = "https://data.epa.gov/efservice/BR_REPORTING/rows/{start}:{end}/JSON"
PAGE_SIZE = 2000
D_CODE_RE = re.compile(r"D\d{3}")

LIMITS = [
    "This is a sample of the BR_REPORTING table pulled on one date, not the whole table.",
    "BR_REPORTING is an annual filing, typically 12-18 months lagged at publication.",
    "Eligibility here means 'a receiver in this same sample has recorded recovery-type "
    "receipt history for this exact federal waste code' -- necessary, not sufficient, "
    "for the row's waste to actually be diverted.",
    "'Divertible' means 'passes this gate', not 'will be diverted' -- no permit, capacity, "
    "logistics, or cost check is performed.",
]


def paginate_raw(total_rows):
    """Pull `total_rows` rows of BR_REPORTING, unfiltered, in PAGE_SIZE pages.
    Caches each page to CORPUS_DIR so a scan is re-runnable offline."""
    import requests

    os.makedirs(CORPUS_DIR, exist_ok=True)
    rows = []
    start = 0
    page_num = 0
    while start < total_rows:
        end = min(start + PAGE_SIZE, total_rows)
        url = BASE_URL.format(start=start, end=end)
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        page_rows = resp.json()
        page_path = os.path.join(CORPUS_DIR, f"raw_page_{start:06d}_{end:06d}.json")
        with open(page_path, "w") as f:
            json.dump(page_rows, f)
        rows.extend(page_rows)
        page_num += 1
        if not page_rows:
            break  # ran past the end of the table
        start = end
    return rows


def load_cached_raw():
    """Load every cached raw page under CORPUS_DIR, in start-offset order."""
    pages = sorted(glob.glob(os.path.join(CORPUS_DIR, "raw_page_*.json")))
    if not pages:
        raise FileNotFoundError(
            f"No cached pages under {CORPUS_DIR}/ -- run without --offline first "
            "to pull and cache a corpus."
        )
    rows = []
    for path in pages:
        with open(path) as f:
            rows.extend(json.load(f))
    return rows


def d_codes(row):
    return {c for c in CODE_RE.findall(row.get("federal_waste_codes") or "") if D_CODE_RE.fullmatch(c)}


def row_tons(row):
    for field in ("shipped_tons", "generation_tons"):
        value = row.get(field)
        if value not in (None, ""):
            try:
                return float(value)
            except ValueError:
                continue
    return 0.0


def compute_summary(rows, meta):
    """Apply the existing eligibility rule (recovery-type management_category +
    exact shared federal waste code) across `rows`, corpus-wide: a disposal-bound
    D-code row is divertible if *any* row in the same corpus shows a receiver with
    a recovery-type receipt for that exact code."""
    recovery_codes_to_receivers = {}
    for row in rows:
        if row.get("management_category") not in RECOVERY_CATEGORIES:
            continue
        receiver_id = row.get("receiver_id")
        if not receiver_id:
            continue
        for code in d_codes(row):
            recovery_codes_to_receivers.setdefault(code, set()).add(receiver_id)

    disposal_bound = []
    for row in rows:
        if row.get("management_category") in RECOVERY_CATEGORIES:
            continue
        codes = d_codes(row)
        if codes:
            disposal_bound.append((row, codes))

    divertible_rows = []
    divertible_tons = 0.0
    for row, codes in disposal_bound:
        matching_receivers = set()
        for code in codes:
            matching_receivers |= recovery_codes_to_receivers.get(code, set())
        if matching_receivers:
            divertible_rows.append(row)
            divertible_tons += row_tons(row)

    total_disposal_tons = sum(row_tons(row) for row, _ in disposal_bound)

    return {
        "meta": meta,
        "rows_scanned": len(rows),
        "disposal_bound_dcode_rows": len(disposal_bound),
        "divertible_rows": len(divertible_rows),
        "divertible_tons": round(divertible_tons, 4),
        "total_disposal_bound_dcode_tons": round(total_disposal_tons, 4),
        "distinct_recovery_receivers_seen": len({r for rs in recovery_codes_to_receivers.values() for r in rs}),
        "limits": LIMITS,
    }


def print_report(summary):
    print(f"Rows scanned:                       {summary['rows_scanned']}")
    print(f"Disposal-bound rows carrying D-codes: {summary['disposal_bound_dcode_rows']}")
    print(f"  of which divertible (gate passes):  {summary['divertible_rows']}")
    print(f"  divertible tons:                    {summary['divertible_tons']}")
    print(f"  (of {summary['total_disposal_bound_dcode_tons']} total disposal-bound D-code tons)")
    print(f"Distinct recovery-type receivers seen: {summary['distinct_recovery_receivers_seen']}")
    print(f"Pull date: {summary['meta']['pull_date']}   Sample size: {summary['meta']['sample_size']}")
    print()
    print("Honest limits on this number:")
    for line in summary["limits"]:
        print(f"  - {line}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="recompute from cached pages, no network call")
    parser.add_argument("--rows", type=int, default=8000, help="total rows to pull (ignored with --offline)")
    args = parser.parse_args()

    if args.offline:
        rows = load_cached_raw()
        with open(META_PATH) as f:
            meta = json.load(f)
    else:
        rows = paginate_raw(args.rows)
        meta = {
            "source": BASE_URL.format(start=0, end=args.rows),
            "pull_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "sample_size": len(rows),
        }
        with open(META_PATH, "w") as f:
            json.dump(meta, f, indent=2)
            f.write("\n")

    summary = compute_summary(rows, meta)
    with open(SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    print_report(summary)


if __name__ == "__main__":
    main()
