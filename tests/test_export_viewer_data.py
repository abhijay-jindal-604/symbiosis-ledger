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
            assert claim.get("allocated_tons") == src.get("allocated_tons")
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


def test_trace_view_contract_tool_calls_are_exported_in_full(monkeypatch):
    """web/index.html renders each tool call as name(arguments) -> result.

    The rendered trace is the demo's central evidence that the agent used
    tools rather than answering blind, so if the exporter ever stops
    carrying these three keys the view degrades to an empty chain with no
    error. Fail here instead.
    """
    _cd_repo_root(monkeypatch)
    data = export_viewer_data.build_data()
    split = next(s for s in data["streams"] if s["stream_id"] == "ALD000622464-D009-W403-2009")

    calls = split["negotiation_log"]["attempts"][-1]["tool_calls"]
    assert calls, "the split stream's resolution must carry its real tool calls"
    for call in calls:
        assert call["name"], "each tool call needs a name to render a signature"
        assert "arguments" in call
        assert "result" in call

    # The self-verification step is what the trace highlights; it must be
    # identifiable by name and carry the arithmetic verdict the view shows.
    verify = [c for c in calls if c["name"] == "check_allocation"]
    assert verify, "expected the agent to have verified its own allocation"
    assert verify[-1]["result"].get("ok") is True
    assert verify[-1]["result"].get("message")


def test_plan_view_contract_exclusions_carry_a_reason_and_date(monkeypatch):
    """The planner view's exclusion block quotes why a candidate was dropped.

    'Excluded from memory' is only persuasive with the recorded reason and
    date beside it, so both must survive the export.
    """
    _cd_repo_root(monkeypatch)
    data = export_viewer_data.build_data()
    with_skips = [s for s in data["streams"] if (s.get("plan") or {}).get("skipped")]
    assert with_skips, "expected at least one stream with a remembered rejection"

    for stream in with_skips:
        for skip in stream["plan"]["skipped"]:
            assert skip["candidate"]
            assert skip["rejection"]["reason"], "exclusion must say why"
            assert skip["rejection"]["date"], "exclusion must say when"


def test_ranking_view_contract_candidates_carry_receipt_counts(monkeypatch):
    """The ranking meters are drawn from receipt_count, and the tiebreak note
    is shown only when every candidate has zero receipts -- so both fields
    must be present and numeric for every candidate."""
    _cd_repo_root(monkeypatch)
    data = export_viewer_data.build_data()
    for stream in data["streams"]:
        for cand in (stream.get("plan") or {}).get("candidates", []):
            assert isinstance(cand["receipt_count"], (int, float))
            assert isinstance(cand["specificity"], (int, float))
            assert cand["receiver_id"], "the view prints the real handler id"
