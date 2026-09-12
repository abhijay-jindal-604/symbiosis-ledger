import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

from manifest_render import load_receivers, load_snapshot_rows, render, resolved_claims
from stream_io import load_stream

STREAM_PATH = os.path.join(os.path.dirname(__file__), "..", "streams",
                            "AK8570028649-D009-W301-2001.yaml")
SPLIT_STREAM_PATH = os.path.join(os.path.dirname(__file__), "..", "streams",
                                  "ALD000622464-D009-W403-2009.yaml")


def _render():
    stream = load_stream(STREAM_PATH)
    receivers = load_receivers()
    snapshot_rows = load_snapshot_rows()
    return render(stream, receivers, snapshot_rows), stream


def test_manifest_carries_real_generator_and_receiver_identifiers():
    doc, stream = _render()
    assert stream["generator"]["handler_id"] in doc
    assert stream["generator"]["handler_name"] in doc
    for claim in stream["claims"]:
        if (claim.get("allocated_tons") or 0) > 0:
            receiver = load_receivers()[claim["claimant"]]
            assert receiver["handler_id"] in doc
            assert receiver["display_name"] in doc


def test_item_20_is_blank_and_captioned():
    doc, _ = _render()
    assert "NOT TRANSMITTED TO ANY REAL FACILITY" in doc
    assert doc.count("[ intentionally left blank ]") == 3


def test_waste_codes_and_allocated_tons_are_real():
    doc, stream = _render()
    assert stream["waste"]["federal_waste_codes"] in doc
    allocated = [c["allocated_tons"] for c in stream["claims"] if (c.get("allocated_tons") or 0) > 0]
    assert allocated
    assert str(allocated[0]) in doc


def test_render_with_two_positive_claims_requires_an_explicit_claim():
    """Regression test for a real bug found while rendering the second demo
    stream's genuine two-way RESOLVED_SPLIT: render() used to silently pick
    the first positively-allocated claim and drop the other recipient's
    shipment entirely from the manifest -- a real EPA manifest is
    shipment-specific, so a two-way split needs two manifests, not one that
    quietly omits half the story. render() now refuses to guess."""
    stream = load_stream(SPLIT_STREAM_PATH)
    receivers = load_receivers()
    snapshot_rows = load_snapshot_rows()
    claims = resolved_claims(stream)
    assert len(claims) == 2  # this stream's whole point: a genuine 2-way split

    try:
        render(stream, receivers, snapshot_rows)
        assert False, "expected ValueError when claim= is omitted and there are 2+ positive claims"
    except ValueError:
        pass


def test_render_split_stream_produces_a_correct_manifest_per_claimant():
    stream = load_stream(SPLIT_STREAM_PATH)
    receivers = load_receivers()
    snapshot_rows = load_snapshot_rows()

    for claim in resolved_claims(stream):
        doc = render(stream, receivers, snapshot_rows, claim=claim)
        receiver = receivers[claim["claimant"]]
        assert receiver["handler_id"] in doc
        assert receiver["display_name"] in doc
        assert str(claim["allocated_tons"]) in doc
        # this claimant's manifest must not silently carry the *other*
        # claimant's allocation figure as if it were this shipment's total
        other = [c for c in resolved_claims(stream) if c is not claim][0]
        if other["allocated_tons"] != claim["allocated_tons"]:
            assert f'>{other["allocated_tons"]} tons<' not in doc
