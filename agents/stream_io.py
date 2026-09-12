"""Canonical serializer for streams/*.yaml. Every writer routes through
write_stream()/load_stream() so two writers never produce phantom diffs
from differing key order.
"""
import yaml

TOP_LEVEL_ORDER = [
    "stream_id", "generator", "waste", "current_disposition",
    "status", "claims", "resolution",
]
GENERATOR_ORDER = ["handler_id", "handler_name", "location"]
WASTE_ORDER = [
    "federal_waste_codes", "form_code", "description",
    "available_tons", "report_cycle",
]
DISPOSITION_ORDER = ["management_category"]
CLAIM_ORDER = [
    "claimant", "requested_tons", "allocated_tons", "schedule",
    "disclosed_constraint",
]
RESOLUTION_ORDER = [
    "method", "resolved_by", "feasible", "explanation", "log", "timestamp",
]


def _ordered(d, order):
    if d is None:
        return None
    out = {}
    for k in order:
        if k in d:
            out[k] = d[k]
    for k in d:
        if k not in out:
            out[k] = d[k]
    return out


def _ordered_claim(claim):
    return _ordered(claim, CLAIM_ORDER)


def canonicalize(stream):
    """Return a new dict with every level in canonical key order and
    claims sorted ascending by claimant."""
    out = _ordered(stream, TOP_LEVEL_ORDER)
    if out.get("generator") is not None:
        out["generator"] = _ordered(out["generator"], GENERATOR_ORDER)
    if out.get("waste") is not None:
        out["waste"] = _ordered(out["waste"], WASTE_ORDER)
    if out.get("current_disposition") is not None:
        out["current_disposition"] = _ordered(out["current_disposition"], DISPOSITION_ORDER)
    claims = out.get("claims") or []
    claims = [_ordered_claim(c) for c in claims]
    claims.sort(key=lambda c: c.get("claimant", ""))
    out["claims"] = claims
    if out.get("resolution") is not None:
        out["resolution"] = _ordered(out["resolution"], RESOLUTION_ORDER)
    return out


def dump_stream(stream) -> str:
    canon = canonicalize(stream)
    return yaml.safe_dump(canon, sort_keys=False, default_flow_style=False, width=100)


def write_stream(path, stream):
    with open(path, "w") as f:
        f.write(dump_stream(stream))


def load_stream(path):
    with open(path) as f:
        return yaml.safe_load(f)
