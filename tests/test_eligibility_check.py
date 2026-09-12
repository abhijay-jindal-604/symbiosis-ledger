import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

from eligibility_check import check_eligibility, load_receivers, load_snapshot

WASTE_CODES = {"D004", "D005", "D006", "D007", "D008", "D009"}


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
