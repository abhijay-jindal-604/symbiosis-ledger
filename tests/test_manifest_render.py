import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

from manifest_render import load_receivers, load_snapshot_rows, render
from stream_io import load_stream

STREAM_PATH = os.path.join(os.path.dirname(__file__), "..", "streams",
                            "AK8570028649-D009-W301-2001.yaml")


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
