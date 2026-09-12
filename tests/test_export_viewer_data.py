import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

import export_viewer_data
from stream_io import load_stream

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
SPLIT_STREAM = os.path.join(REPO_ROOT, "streams", "ALD000622464-D009-W403-2009.yaml")


def _cd_repo_root(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_exported_allocation_matches_the_real_resolved_stream(monkeypatch):
    _cd_repo_root(monkeypatch)
    data = export_viewer_data.build_data()
    source = load_stream("streams/ALD000622464-D009-W403-2009.yaml")

    exported = next(s for s in data["streams"] if s["stream_id"] == source["stream_id"])
    assert exported["resolution"]["method"] == source["resolution"]["method"] == "negotiated_split"
    assert exported["resolution"]["explanation"] == source["resolution"]["explanation"]

    exported_by_claimant = {c["claimant"]: c["allocated_tons"] for c in exported["claims"]}
    source_by_claimant = {c["claimant"]: c["allocated_tons"] for c in source["claims"]}
    assert exported_by_claimant == source_by_claimant == {"kiln-b": 20.0, "wwtp-c": 28.0135}


def test_exported_receiver_handler_ids_are_real(monkeypatch):
    _cd_repo_root(monkeypatch)
    data = export_viewer_data.build_data()
    receivers = export_viewer_data.load_receivers()

    assert set(data["receivers"].keys()) == set(receivers.keys())
    for alias, info in receivers.items():
        assert data["receivers"][alias]["handler_id"] == info["handler_id"]


def test_every_exported_field_traces_to_a_source_artifact(monkeypatch):
    """The exporter must not invent fields: every claim/resolution value in
    the export is byte-identical to what's on disk in streams/*.yaml, and
    every negotiation_log (when present) is the exact committed log file."""
    _cd_repo_root(monkeypatch)
    data = export_viewer_data.build_data()

    for exported in data["streams"]:
        source = load_stream(exported["source_file"])
        assert exported["stream_id"] == source["stream_id"]
        assert exported["generator"] == source["generator"]
        assert exported["waste"] == source["waste"]
        assert exported["status"] == source["status"]

        source_claims_by_claimant = {c["claimant"]: c for c in (source.get("claims") or [])}
        for claim in exported["claims"]:
            src = source_claims_by_claimant[claim["claimant"]]
            assert claim["allocated_tons"] == src.get("allocated_tons")
            assert claim["disclosed_constraint"] == src.get("disclosed_constraint")

        if source.get("resolution"):
            assert exported["resolution"]["explanation"] == source["resolution"]["explanation"]
            assert exported["resolution"]["log"] == source["resolution"].get("log")
        else:
            assert exported["resolution"] is None


def test_unresolved_stream_has_no_plan_acceptance_side_effects(monkeypatch, tmp_path):
    """Exporting must never write a receiver profile -- it only ranks
    candidates (planner.plan_stream), it must never propose to one."""
    _cd_repo_root(monkeypatch)
    import orchestrate
    monkeypatch.setattr(orchestrate, "PROFILES_DIR", str(tmp_path / "profiles"))

    export_viewer_data.build_data()

    assert not os.path.exists(str(tmp_path / "profiles")) or not os.listdir(str(tmp_path / "profiles"))
