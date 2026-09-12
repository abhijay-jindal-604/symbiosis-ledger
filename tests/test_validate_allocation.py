import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

from validate_allocation import UnevaluableError, validate

VALIDATOR_PATH = os.path.join(os.path.dirname(__file__), "..", "agents", "validate_allocation.py")


def _stream(available_tons, claims):
    return {
        "waste": {"available_tons": available_tons},
        "claims": claims,
        "resolution": {"method": "negotiated_split"},
    }


def test_valid_allocation_is_good():
    ok, msg = validate(_stream(24.1325, [
        {"claimant": "kiln-b", "allocated_tons": 0.0},
        {"claimant": "wwtp-c", "allocated_tons": 24.1325},
    ]))
    assert ok is True


def test_overallocation_is_bad():
    ok, msg = validate(_stream(24.1325, [
        {"claimant": "kiln-b", "allocated_tons": 24.1325},
        {"claimant": "wwtp-c", "allocated_tons": 24.1325},
    ]))
    assert ok is False
    assert "exceeds available" in msg


def test_negative_allocation_is_bad():
    ok, msg = validate(_stream(24.1325, [
        {"claimant": "kiln-b", "allocated_tons": -1.0},
        {"claimant": "wwtp-c", "allocated_tons": 24.1325},
    ]))
    assert ok is False
    assert "negative" in msg


def test_unresolved_stream_is_unevaluable():
    stream = {"waste": {"available_tons": 24.1325}, "claims": [], "resolution": None}
    try:
        validate(stream)
        assert False, "expected UnevaluableError"
    except UnevaluableError:
        pass


def test_missing_allocated_tons_is_unevaluable():
    stream = _stream(24.1325, [{"claimant": "kiln-b"}])
    try:
        validate(stream)
        assert False, "expected UnevaluableError"
    except UnevaluableError:
        pass


def test_cli_exit_codes():
    good = os.path.join(os.path.dirname(__file__), "..", "streams",
                         "AK8570028649-D009-W301-2001.yaml")
    rc = subprocess.run([sys.executable, VALIDATOR_PATH, good]).returncode
    assert rc == 0

    rc = subprocess.run([sys.executable, VALIDATOR_PATH, "streams/does-not-exist.yaml"]).returncode
    assert rc == 2

    rc = subprocess.run([sys.executable, VALIDATOR_PATH]).returncode
    assert rc == 2
