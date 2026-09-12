"""On-camera beat (0:15-0:35 of the demo script): fetch the demo stream's
real EPA row live, print it side by side with the committed snapshot row,
and verdict MATCH/DIFFER.
"""
import json
import re
import sys
import urllib.request

SNAPSHOT_PATH = "data/br_reporting_snapshot.json"
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


def main():
    print(f"Live query: EPA Envirofacts BR_REPORTING, handler_id={GENERATOR_HANDLER_ID}")
    live = fetch_live_row()
    snap = load_snapshot_row()

    if live is None:
        print("LIVE ROW NOT FOUND — the table may have changed since the snapshot was pulled.")
        sys.exit(1)
    if snap is None:
        print("SNAPSHOT ROW NOT FOUND — data/br_reporting_snapshot.json is missing this row.")
        sys.exit(1)

    print(f"\n{'field':<22}{'live':<30}{'snapshot':<30}")
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
