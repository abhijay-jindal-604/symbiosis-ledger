import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

import corpus_scan


def _row(receiver_id, management_category, federal_waste_codes, shipped_tons):
    return {
        "receiver_id": receiver_id,
        "management_category": management_category,
        "federal_waste_codes": federal_waste_codes,
        "shipped_tons": shipped_tons,
    }


# A known, hand-computed fixture corpus:
#   row A: recovery receipt at receiver X for D001 and D002
#   row B: disposal-bound, D001 -- divertible (X has a D001 recovery receipt)
#   row C: disposal-bound, D005 -- NOT divertible (no recovery receiver for D005)
#   row D: disposal-bound, but no D-code at all (F003 only) -- excluded entirely
#   row E: recovery receipt with no receiver_id -- must not enter the index
FIXTURE_ROWS = [
    _row("RECEIVER-X", "METALS RECOVERY", "D001D002", "0"),
    _row("GEN-1", "LANDFILL", "D001", "10.0"),
    _row("GEN-2", "INCINERATION", "D005", "5.0"),
    _row("GEN-3", "LANDFILL", "F003", "7.0"),
    _row(None, "SOLVENTS RECOVERY", "D001", "0"),
]


def test_compute_summary_matches_hand_computed_answer():
    summary = corpus_scan.compute_summary(FIXTURE_ROWS, meta={"pull_date": "2026-01-01", "sample_size": 5})

    assert summary["rows_scanned"] == 5
    assert summary["disposal_bound_dcode_rows"] == 2  # rows B and C; D excluded (no D-code)
    assert summary["divertible_rows"] == 1  # row B only
    assert summary["divertible_tons"] == 10.0
    assert summary["total_disposal_bound_dcode_tons"] == 15.0  # rows B + C
    assert summary["distinct_recovery_receivers_seen"] == 1  # only RECEIVER-X; row E had no receiver_id


def test_d_codes_extracts_only_d_codes_from_compound_string():
    row = {"federal_waste_codes": "F003D009K001"}
    assert corpus_scan.d_codes(row) == {"D009"}


def test_row_tons_falls_back_to_generation_tons():
    assert corpus_scan.row_tons({"shipped_tons": "", "generation_tons": "3.5"}) == 3.5
    assert corpus_scan.row_tons({"shipped_tons": "2.0", "generation_tons": "9.0"}) == 2.0
    assert corpus_scan.row_tons({}) == 0.0


def test_offline_recompute_matches_cached_pull(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(corpus_scan, "CORPUS_DIR", "data/corpus")
    monkeypatch.setattr(corpus_scan, "META_PATH", "data/corpus/meta.json")
    monkeypatch.setattr(corpus_scan, "SUMMARY_PATH", "data/corpus_summary.json")

    os.makedirs("data/corpus")
    with open("data/corpus/raw_page_000000_000005.json", "w") as f:
        json.dump(FIXTURE_ROWS, f)
    meta = {"source": "fixture", "pull_date": "2026-01-01", "sample_size": 5}
    with open("data/corpus/meta.json", "w") as f:
        json.dump(meta, f)

    rows = corpus_scan.load_cached_raw()
    assert len(rows) == 5

    summary = corpus_scan.compute_summary(rows, meta)
    with open("data/corpus_summary.json", "w") as f:
        json.dump(summary, f)

    # Recompute from the cache alone (no network) and confirm it reproduces
    # the exact committed summary -- this is the real acceptance check.
    reloaded_rows = corpus_scan.load_cached_raw()
    with open("data/corpus/meta.json") as f:
        reloaded_meta = json.load(f)
    recomputed = corpus_scan.compute_summary(reloaded_rows, reloaded_meta)

    with open("data/corpus_summary.json") as f:
        committed = json.load(f)

    assert recomputed == committed


def test_load_cached_raw_raises_clearly_when_no_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(corpus_scan, "CORPUS_DIR", "data/corpus")
    os.makedirs("data/corpus")
    try:
        corpus_scan.load_cached_raw()
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass
