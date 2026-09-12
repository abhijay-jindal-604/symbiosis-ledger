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
#   row A: recovery receipt at receiver X for D001 and D002 (X's full profile: {D001, D002})
#   row B: disposal-bound, D001 -- divertible both ways (X covers D001 alone)
#   row C: disposal-bound, D005 -- NOT divertible either way (no recovery receiver for D005)
#   row D: disposal-bound, but no D-code at all (F003 only) -- excluded entirely
#   row E: recovery receipt with no receiver_id -- must not enter the index
#   row F: disposal-bound, D001+D003 (compound) -- divertible any-code (X has D001),
#          but NOT divertible full-profile (no single receiver covers both D001 and D003)
FIXTURE_ROWS = [
    _row("RECEIVER-X", "METALS RECOVERY", "D001D002", "0"),
    _row("GEN-1", "LANDFILL", "D001", "10.0"),
    _row("GEN-2", "INCINERATION", "D005", "5.0"),
    _row("GEN-3", "LANDFILL", "F003", "7.0"),
    _row(None, "SOLVENTS RECOVERY", "D001", "0"),
    _row("GEN-4", "LANDFILL", "D001D003", "4.0"),
]


def test_compute_summary_matches_hand_computed_answer():
    summary = corpus_scan.compute_summary(FIXTURE_ROWS, meta={"pull_date": "2026-01-01", "sample_size": 6})

    assert summary["rows_scanned"] == 6
    assert summary["disposal_bound_dcode_rows"] == 3  # rows B, C, F; D excluded (no D-code)
    assert summary["divertible_rows_any_code"] == 2  # rows B and F (each has a D001 match)
    assert summary["divertible_tons_any_code"] == 14.0  # rows B (10.0) + F (4.0)
    assert summary["divertible_rows_full_profile"] == 1  # row B only -- F's D003 isn't covered by X
    assert summary["divertible_tons_full_profile"] == 10.0
    assert summary["total_disposal_bound_dcode_tons"] == 19.0  # rows B + C + F
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
    with open("data/corpus/raw_page_000000_000006.json", "w") as f:
        json.dump(FIXTURE_ROWS, f)
    meta = {"source": "fixture", "pull_date": "2026-01-01", "sample_size": 6}
    with open("data/corpus/meta.json", "w") as f:
        json.dump(meta, f)

    rows = corpus_scan.load_cached_raw()
    assert len(rows) == 6

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
