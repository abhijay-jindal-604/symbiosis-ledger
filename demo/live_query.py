"""On-camera beat (0:15-0:35 of the demo script): fetch the demo stream's
real EPA row live, print it side by side with the committed snapshot row,
and verdict MATCH/DIFFER.

Phase 14 demo-path caching: this build hit real quota/rate-limit trouble
during development, and while EPA's Envirofacts endpoint isn't rate-limited
the same way, a flaky or slow response here is exactly the kind of thing
that costs a take. The live call stays the default; if it fails, this falls
back to the last live response cached on disk at CACHE_PATH and labels that
on stdout, per the addendum's still-binding rule: if we replay, we say
"replay", unprompted.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date

SNAPSHOT_PATH = "data/br_reporting_snapshot.json"
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "live_query_epa_row.json")
GENERATOR_HANDLER_ID = "AK8570028649"
RECEIVER_ID = "IDD073114654"
SHIPPED_TONS = "24.1325"

FIELDS_TO_COMPARE = [
    "handler_id", "handler_name", "receiver_id", "federal_waste_codes",
    "form_code", "management_category", "shipped_tons", "report_cycle",
]


def fetch_live_row():
    # Filtering by receiver_id, not handler_id: confirmed by direct testing that
    # BR_REPORTING's handler_id path-filter and its unfiltered/receiver_id-filtered
    # results can disagree for the same underlying row (likely replica lag on
    # data.epa.gov). receiver_id filtering reliably found this exact row across
    # repeated independent pulls; handler_id filtering did not.
    url = f"https://data.epa.gov/efservice/BR_REPORTING/receiver_id/{RECEIVER_ID}/rows/0:2000/JSON"
    with urllib.request.urlopen(url, timeout=30) as r:
        rows = json.loads(r.read().decode())
    for row in rows:
        if row.get("handler_id") == GENERATOR_HANDLER_ID and row.get("shipped_tons") == SHIPPED_TONS:
            return row
    return None


def load_snapshot_row():
    with open(SNAPSHOT_PATH) as f:
        snap = json.load(f)
    for row in snap["rows"]:
        if row.get("handler_id") == GENERATOR_HANDLER_ID and row.get("receiver_id") == RECEIVER_ID:
            return row
    return None


def _load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            return json.load(f)
    return None


def _save_cache(row):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp_path = f"{CACHE_PATH}.tmp"
    with open(tmp_path, "w") as f:
        json.dump({"row": row, "verified_date": date.today().isoformat()}, f, indent=2)
    os.replace(tmp_path, CACHE_PATH)


def get_row_live_or_cached():
    """Returns (row, was_cached). Tries the live EPA call first; falls back
    to the cache on any failure (network down, endpoint error, row not
    found). Raises only if neither a live row nor a cache is available."""
    try:
        row = fetch_live_row()
    except Exception as e:
        print(f"Live fetch failed ({e}); falling back to cache.")
        row = None

    if row is not None:
        _save_cache(row)
        return row, False

    cache = _load_cache()
    if cache is None:
        return None, False
    print(f"[cached response, live-verified {cache['verified_date']}]")
    return cache["row"], True


def main():
    print(f"Live query: EPA Envirofacts BR_REPORTING, handler_id={GENERATOR_HANDLER_ID}")
    live, was_cached = get_row_live_or_cached()
    snap = load_snapshot_row()

    if live is None:
        print("LIVE ROW NOT FOUND — the table may have changed since the snapshot was pulled, "
              "and no cached response is available either.")
        sys.exit(1)
    if snap is None:
        print("SNAPSHOT ROW NOT FOUND — data/br_reporting_snapshot.json is missing this row.")
        sys.exit(1)

    live_col = "live (cached)" if was_cached else "live"
    print(f"\n{'field':<22}{live_col:<30}{'snapshot':<30}")
    all_match = True
    for field in FIELDS_TO_COMPARE:
        lv, sv = str(live.get(field)), str(snap.get(field))
        marker = "" if lv == sv else "  <-- DIFFERS"
        if lv != sv:
            all_match = False
        print(f"{field:<22}{lv:<30}{sv:<30}{marker}")

    print()
    if all_match:
        print("MATCH")
    else:
        print("DIFFER")
        sys.exit(1)


if __name__ == "__main__":
    main()
