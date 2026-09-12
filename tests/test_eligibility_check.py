import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

from eligibility_check import check_eligibility, load_receivers, load_snapshot

WASTE_CODES = {"D004", "D005", "D006", "D007", "D008", "D009"}
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_kiln_b_is_eligible():
    receivers = load_receivers()
    snapshot = load_snapshot()
    ok, msg = check_eligibility("kiln-b", receivers, snapshot, WASTE_CODES)
    assert ok is True
    assert "ELIGIBLE" in msg


def test_wwtp_c_is_eligible():
    receivers = load_receivers()
    snapshot = load_snapshot()
    ok, msg = check_eligibility("wwtp-c", receivers, snapshot, WASTE_CODES)
    assert ok is True
    assert "ELIGIBLE" in msg


def test_recycler_d_is_denied():
    receivers = load_receivers()
    snapshot = load_snapshot()
    ok, msg = check_eligibility("recycler-d", receivers, snapshot, WASTE_CODES)
    assert ok is False
    assert "DENIED" in msg


def test_receivers_json_matches_expected_eligibility():
    """Guards against the snapshot silently changing under the demo's feet:
    if a receiver's real eligibility ever flips, this test goes red instead
    of the demo failing on recording night."""
    receivers = load_receivers()
    snapshot = load_snapshot()
    for claimant, info in receivers.items():
        ok, _ = check_eligibility(claimant, receivers, snapshot, WASTE_CODES)
        expected = info["expected_eligibility"] == "ELIGIBLE"
        assert ok == expected, f"{claimant}: expected {info['expected_eligibility']}, got eligible={ok}"


def test_unknown_claimant_is_denied():
    receivers = load_receivers()
    snapshot = load_snapshot()
    ok, msg = check_eligibility("ghost-claimant", receivers, snapshot, WASTE_CODES)
    assert ok is False


def test_readme_documented_denial_command_works():
    """The README's exact documented command for the recycler-d denial beat
    passes --stream explicitly, because recycler-d's denial-evidence claim
    was deliberately never merged into any stream file on main (its PR #3
    stays open as evidence). Runs the actual CLI as a subprocess from the
    repo root, exactly as a reader would copy-paste it.

    An earlier version of this fix tried a "fall back to the one stream
    file present" heuristic in _find_stream_for_claimant instead of fixing
    the README -- that broke again the moment a second real stream file was
    added to the repo (see the two tests below), which is exactly why the
    permanent fix is an explicit --stream, not a guess."""
    result = subprocess.run(
        [sys.executable, "agents/eligibility_check.py", "--claimant", "recycler-d",
         "--stream", "streams/AK8570028649-D009-W301-2001.yaml"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ELIGIBILITY DENIED" in result.stdout
    assert "NED981723513" in result.stdout


def test_find_stream_for_claimant_prefers_a_claims_match(tmp_path, monkeypatch):
    from eligibility_check import _find_stream_for_claimant
    from stream_io import write_stream

    (tmp_path / "streams").mkdir()
    monkeypatch.chdir(tmp_path)

    blank = {"stream_id": "X", "generator": {}, "waste": {}, "current_disposition": {}, "resolution": None}
    write_stream("streams/a.yaml", {**blank, "status": "CLAIMED", "claims": [{"claimant": "kiln-b"}]})
    write_stream("streams/b.yaml", {**blank, "status": "UNCLAIMED", "claims": []})

    assert _find_stream_for_claimant("kiln-b") == "streams/a.yaml"


def test_find_stream_for_claimant_returns_none_with_multiple_streams_and_no_match(tmp_path, monkeypatch):
    """Pins the exact boundary this repo actually hit: a fallback that
    assumes "exactly one stream file" stops working the moment a second
    real stream is added, so a claimant whose claim was never merged
    anywhere (like recycler-d) can no longer be auto-discovered once
    there's more than one stream -- --stream must be passed explicitly.
    This is intentional: silently guessing which of several streams an
    unmatched claimant "probably" means would be worse than a clear
    "not found"."""
    from eligibility_check import _find_stream_for_claimant
    from stream_io import write_stream

    (tmp_path / "streams").mkdir()
    monkeypatch.chdir(tmp_path)

    blank = {"stream_id": "X", "generator": {}, "waste": {}, "current_disposition": {},
             "status": "UNCLAIMED", "claims": [], "resolution": None}
    write_stream("streams/a.yaml", blank)
    write_stream("streams/b.yaml", blank)

    assert _find_stream_for_claimant("recycler-d") is None
