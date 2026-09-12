import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

import orchestrate

STREAM_PATH = os.path.join(os.path.dirname(__file__), "..", "streams",
                            "AK8570028649-D009-W301-2001.yaml")


def _isolate_profiles(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrate, "PROFILES_DIR", str(tmp_path / "profiles"))


def test_ineligible_claimant_is_denied_and_logged(monkeypatch, tmp_path):
    _isolate_profiles(monkeypatch, tmp_path)
    result = orchestrate.propose(STREAM_PATH, "recycler-d")
    assert result["proposed"] is False
    assert "DENIED" in result["reason"]
    profile = orchestrate.load_profile("NED981723513")
    assert len(profile["rejected_claims"]) == 1
    assert profile["rejected_claims"][0]["stream_id"] == "AK8570028649-D009-W301-2001"


def test_second_call_skips_from_memory_without_duplicating(monkeypatch, tmp_path, capsys):
    _isolate_profiles(monkeypatch, tmp_path)
    orchestrate.propose(STREAM_PATH, "recycler-d")
    capsys.readouterr()  # discard run 1's output

    result = orchestrate.propose(STREAM_PATH, "recycler-d")
    out = capsys.readouterr().out
    assert result["proposed"] is False
    assert result["reason"].startswith("skipping recycler-d")
    assert "skipping recycler-d" in out

    profile = orchestrate.load_profile("NED981723513")
    assert len(profile["rejected_claims"]) == 1  # not duplicated


def test_eligible_claimant_is_proposed_and_recorded(monkeypatch, tmp_path):
    _isolate_profiles(monkeypatch, tmp_path)
    result = orchestrate.propose(STREAM_PATH, "kiln-b")
    assert result["proposed"] is True
    assert "ELIGIBLE" in result["reason"]
    profile = orchestrate.load_profile("IND000646943")
    assert "AK8570028649-D009-W301-2001" in profile["accepted_streams"]


def test_repeated_acceptance_does_not_duplicate(monkeypatch, tmp_path):
    _isolate_profiles(monkeypatch, tmp_path)
    orchestrate.propose(STREAM_PATH, "kiln-b")
    orchestrate.propose(STREAM_PATH, "kiln-b")
    profile = orchestrate.load_profile("IND000646943")
    assert profile["accepted_streams"].count("AK8570028649-D009-W301-2001") == 1


def test_unknown_claimant_is_not_proposed(monkeypatch, tmp_path):
    _isolate_profiles(monkeypatch, tmp_path)
    result = orchestrate.propose(STREAM_PATH, "nonexistent-claimant")
    assert result["proposed"] is False
    assert "unknown claimant" in result["reason"]
