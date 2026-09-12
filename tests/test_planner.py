import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

import orchestrate
import planner
from stream_io import write_stream

# Isolated fixtures, not the repo's live receivers.json/snapshot/streams --
# see agents/planner.py's docstring for why recycler-d's real-world zero
# receipts still needs an isolated stand-in here rather than the live file
# count (that exact mistake broke PRs #7/#8 before).
RECEIVERS = {
    "kiln-b": {"handler_id": "R-KILN", "role_label": "metals recovery facility"},
    "wwtp-c": {"handler_id": "R-WWTP", "role_label": "environmental treatment facility"},
    "recycler-d": {"handler_id": "R-RCYD", "role_label": "solvent recycler"},
}

SNAPSHOT = [
    # kiln-b: two real METALS RECOVERY receipts of D009, none of F003.
    {"receiver_id": "R-KILN", "management_category": "METALS RECOVERY",
     "federal_waste_codes": "D009", "shipped_tons": "1.0", "report_cycle": 2020},
    {"receiver_id": "R-KILN", "management_category": "METALS RECOVERY",
     "federal_waste_codes": "D009", "shipped_tons": "2.0", "report_cycle": 2021},
    # wwtp-c: one real METALS RECOVERY receipt of D009, none of F003.
    {"receiver_id": "R-WWTP", "management_category": "METALS RECOVERY",
     "federal_waste_codes": "D002D009", "shipped_tons": "0.5", "report_cycle": 2019},
    # recycler-d: no rows at all.
]


def _write_stream(path, stream_id, codes):
    write_stream(str(path), {
        "stream_id": stream_id,
        "generator": {"handler_id": "GEN0000000001", "handler_name": "TEST GENERATOR", "location": "TEST, ZZ"},
        "waste": {"federal_waste_codes": codes, "form_code": "W000",
                   "description": "test fixture", "available_tons": 10.0, "report_cycle": 2026},
        "current_disposition": {"management_category": "LANDFILL"},
        "status": "UNCLAIMED",
        "claims": [],
        "resolution": None,
    })


def _isolate_profiles(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrate, "PROFILES_DIR", str(tmp_path / "profiles"))


def test_ranking_is_deterministic_and_correctly_ordered(monkeypatch, tmp_path):
    _isolate_profiles(monkeypatch, tmp_path)
    stream_path = tmp_path / "fresh.yaml"
    _write_stream(stream_path, "TEST-STREAM-1", "F003D009")

    plan = planner.plan_stream(str(stream_path), receivers=RECEIVERS, snapshot=SNAPSHOT)

    assert plan["primary_code"] == "F003"
    order = [c["candidate"] for c in plan["candidates"]]
    # recycler-d ties everyone at 0 real receipts of the primary code (F003)
    # but wins the ranking tiebreak on its own declared specialty; kiln-b
    # and wwtp-c, tied with each other too, break on total tons handled.
    assert order == ["recycler-d", "kiln-b", "wwtp-c"]
    by_alias = {c["candidate"]: c for c in plan["candidates"]}
    assert by_alias["recycler-d"]["specificity"] == 1
    assert by_alias["kiln-b"]["specificity"] == 0
    assert by_alias["kiln-b"]["total_tons_handled"] == 3.0
    assert by_alias["wwtp-c"]["total_tons_handled"] == 0.5

    # Ranking is stable and repeatable, not incidentally ordered.
    plan2 = planner.plan_stream(str(stream_path), receivers=RECEIVERS, snapshot=SNAPSHOT)
    assert [c["candidate"] for c in plan2["candidates"]] == order


def test_denial_removes_candidate_from_next_plan(monkeypatch, tmp_path):
    _isolate_profiles(monkeypatch, tmp_path)
    stream_path = tmp_path / "fresh.yaml"
    _write_stream(stream_path, "TEST-STREAM-2", "F003D009")

    run1 = planner.run_plan(str(stream_path), receivers=RECEIVERS, snapshot=SNAPSHOT)
    assert [a["candidate"] for a in run1["attempts"]] == ["recycler-d", "kiln-b"]
    assert run1["attempts"][0]["proposed"] is False
    assert run1["attempts"][1]["proposed"] is True
    assert run1["accepted"] == "kiln-b"
    assert len(run1["candidates"]) == 3
    assert run1["skipped"] == []

    run2 = planner.run_plan(str(stream_path), receivers=RECEIVERS, snapshot=SNAPSHOT)
    assert len(run2["candidates"]) == len(run1["candidates"]) - 1
    assert [c["candidate"] for c in run2["candidates"]] == ["kiln-b", "wwtp-c"]
    assert len(run2["skipped"]) == 1
    assert run2["skipped"][0]["candidate"] == "recycler-d"
    assert run2["skipped"][0]["rejection"]["stream_id"] == "TEST-STREAM-2"
    # Already accepted last time, re-affirmed on this run without a second denial.
    assert [a["candidate"] for a in run2["attempts"]] == ["kiln-b"]
    assert run2["accepted"] == "kiln-b"


def test_loop_terminates_when_candidates_are_exhausted(monkeypatch, tmp_path):
    _isolate_profiles(monkeypatch, tmp_path)
    stream_path = tmp_path / "unrecognized.yaml"
    _write_stream(stream_path, "TEST-STREAM-3", "F999")  # no receiver has ever handled this code

    result = planner.run_plan(str(stream_path), receivers=RECEIVERS, snapshot=SNAPSHOT)

    assert len(result["attempts"]) == len(result["candidates"]) == 3
    assert all(a["proposed"] is False for a in result["attempts"])


def test_no_eligible_candidate_case_is_explicit(monkeypatch, tmp_path):
    _isolate_profiles(monkeypatch, tmp_path)
    stream_path = tmp_path / "unrecognized.yaml"
    _write_stream(stream_path, "TEST-STREAM-4", "F999")

    result = planner.run_plan(str(stream_path), receivers=RECEIVERS, snapshot=SNAPSHOT)

    assert result["accepted"] is None
    assert result["no_eligible_candidate"] is True


def test_run_succeeds_with_rationale_call_failing(monkeypatch, tmp_path):
    _isolate_profiles(monkeypatch, tmp_path)
    stream_path = tmp_path / "fresh.yaml"
    _write_stream(stream_path, "TEST-STREAM-5", "F003D009")

    def broken_rationale(plan, attempts, accepted):
        raise RuntimeError("model unavailable")

    result = planner.run_plan(str(stream_path), receivers=RECEIVERS, snapshot=SNAPSHOT,
                               rationale_call=broken_rationale)

    assert result["accepted"] == "kiln-b"
    assert result["rationale"] is not None
    assert "unavailable" in result["rationale"]


def test_run_succeeds_with_no_rationale_call_at_all(monkeypatch, tmp_path):
    _isolate_profiles(monkeypatch, tmp_path)
    stream_path = tmp_path / "fresh.yaml"
    _write_stream(stream_path, "TEST-STREAM-6", "F003D009")

    result = planner.run_plan(str(stream_path), receivers=RECEIVERS, snapshot=SNAPSHOT)

    assert result["accepted"] == "kiln-b"
    assert result["rationale"] is None
