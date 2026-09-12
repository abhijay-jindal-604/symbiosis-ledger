"""Renders an EPA Form 8700-22-shaped demo manifest from a resolved stream
file. A plausible facsimile of the Uniform Hazardous Waste Manifest, not a
legally exact reproduction -- populated with the real generator/receiver
identifiers and waste-code data from data/receivers.json and the stream
file itself, never hardcoded demo strings. Item 20 (designated facility
certification of receipt) is always left blank: this document is never
transmitted to any real facility.
"""
import argparse
import html
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stream_io import load_stream

RECEIVERS_PATH = "data/receivers.json"
SNAPSHOT_PATH = "data/br_reporting_snapshot.json"
OUT_DIR = "out"


def load_receivers():
    with open(RECEIVERS_PATH) as f:
        return json.load(f)


def load_snapshot_rows():
    with open(SNAPSHOT_PATH) as f:
        return json.load(f)["rows"]


def find_generator_address(rows, handler_id):
    for row in rows:
        if row.get("handler_id") == handler_id:
            street = ", ".join(p for p in (row.get("location_street1"), row.get("location_street2")) if p)
            city = row.get("location_city") or ""
            state = row.get("location_state") or ""
            zip_ = row.get("location_zip") or ""
            address = f"{street}, {city}, {state} {zip_}".strip(", ").strip()
            return address or None
    return None


def manifest_tracking_number(stream_id):
    # Demo-generated, not an EPA-issued tracking number -- labeled as such.
    return "DEMO-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, stream_id)).split("-")[0].upper()


def resolved_claim(stream):
    for claim in stream.get("claims") or []:
        if (claim.get("allocated_tons") or 0) > 0:
            return claim
    return None


def render(stream, receivers, snapshot_rows):
    e = html.escape
    stream_id = stream["stream_id"]
    generator = stream["generator"]
    waste = stream["waste"]
    resolution = stream.get("resolution") or {}
    claim = resolved_claim(stream)

    generator_address = find_generator_address(snapshot_rows, generator["handler_id"])
    generator_address_html = e(generator_address) if generator_address else (
        '<span class="missing">not available in the committed EPA snapshot</span>'
    )

    if claim:
        receiver_info = receivers.get(claim["claimant"], {})
        facility_name = receiver_info.get("display_name", claim["claimant"])
        facility_epa_id = receiver_info.get("handler_id", "unknown")
        facility_role = receiver_info.get("role_label", "")
        total_qty = claim.get("allocated_tons")
        schedule_text = claim.get("schedule") or ""
        disclosed = claim.get("disclosed_constraint") or ""
    else:
        facility_name = "UNRESOLVED — no designated facility yet"
        facility_epa_id = "n/a"
        facility_role = ""
        total_qty = None
        schedule_text = ""
        disclosed = ""

    tracking_number = manifest_tracking_number(stream_id)

    def row(label, value):
        return f'<div class="field"><div class="field-label">{label}</div><div class="field-value">{value}</div></div>'

    resolution_block = ""
    if resolution:
        resolution_block = f"""
    <section class="audit">
      <h2>Resolution record (audit trail, not part of the EPA form)</h2>
      {row("Status", e(stream.get("status", "")))}
      {row("Resolution method", e(str(resolution.get("method"))))}
      {row("Resolved by", e(str(resolution.get("resolved_by"))))}
      {row("Feasible", e(str(resolution.get("feasible"))))}
      {row("Explanation", e(resolution.get("explanation", "")))}
      {row("Negotiation log", e(str(resolution.get("log"))))}
      {row("Timestamp", e(str(resolution.get("timestamp"))))}
    </section>"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Manifest facsimile — {e(stream_id)}</title>
<style>
  body {{ font-family: Georgia, "Times New Roman", serif; max-width: 820px; margin: 2rem auto;
         padding: 0 1.5rem; color: #1a1a1a; background: #fdfcf9; }}
  .banner {{ background: #7a1f1f; color: #fff; padding: 0.9rem 1.2rem; font-family: system-ui, sans-serif;
            font-weight: 700; border-radius: 4px; margin-bottom: 1.5rem; }}
  .banner small {{ display: block; font-weight: 400; font-size: 0.85rem; margin-top: 0.3rem; }}
  h1 {{ font-size: 1.3rem; border-bottom: 2px solid #1a1a1a; padding-bottom: 0.4rem; }}
  h2 {{ font-size: 1rem; font-family: system-ui, sans-serif; text-transform: uppercase;
       letter-spacing: 0.03em; color: #444; margin-top: 2rem; }}
  section {{ border: 1px solid #ccc; border-radius: 4px; padding: 1rem 1.2rem; margin-bottom: 1rem; }}
  .field {{ margin-bottom: 0.6rem; }}
  .field-label {{ font-family: system-ui, sans-serif; font-size: 0.72rem; text-transform: uppercase;
                 letter-spacing: 0.04em; color: #666; }}
  .field-value {{ font-size: 1.02rem; }}
  .missing {{ color: #999; font-style: italic; }}
  .item-20 {{ background: #fff8f0; border: 2px dashed #b06a00; }}
  .item-20 .field-value {{ min-height: 2rem; border-bottom: 1px solid #b06a00; }}
  .cert-blank {{ color: #b06a00; font-weight: 700; font-family: system-ui, sans-serif; }}
  footer {{ margin-top: 2rem; font-family: system-ui, sans-serif; font-size: 0.8rem; color: #666;
           border-top: 1px solid #ccc; padding-top: 1rem; }}
  .audit {{ background: #f4f6f8; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0 1.5rem; }}
</style>
</head>
<body>

  <div class="banner">
    GENERATED FOR DEMONSTRATION. NOT TRANSMITTED TO ANY REAL FACILITY.
    <small>This is a plausible facsimile of EPA Form 8700-22 (Uniform Hazardous Waste Manifest),
    not a legally exact reproduction, populated with real EPA-published data for demonstration
    purposes only.</small>
  </div>

  <h1>Uniform Hazardous Waste Manifest — demo facsimile</h1>

  <section>
    <h2>Item 1 — Manifest Tracking Number</h2>
    {row("Tracking number (demo-generated, not EPA-issued)", e(tracking_number))}
  </section>

  <section>
    <h2>Item 4 — Generator</h2>
    <div class="grid2">
      {row("Name", e(generator.get("handler_name", "")))}
      {row("EPA ID Number", e(generator.get("handler_id", "")))}
    </div>
    {row("Mailing / Site Address", generator_address_html)}
    {row("Site location (per stream record)", e(generator.get("location", "")))}
  </section>

  <section>
    <h2>Item 5 — Transporter</h2>
    {row("Company Name", '<span class="missing">placeholder — not the point of this demo</span>')}
    {row("EPA ID Number", '<span class="missing">placeholder</span>')}
  </section>

  <section>
    <h2>Item 8 — Designated Facility (resolved receiver)</h2>
    <div class="grid2">
      {row("Facility Name", e(facility_name))}
      {row("EPA ID Number", e(facility_epa_id))}
    </div>
    {row("Role", e(facility_role))}
    {row("Site Address", '<span class="missing">not available in the committed EPA snapshot — BR_REPORTING gives address fields for the handler/generator side of a row, not the receiver side</span>')}
  </section>

  <section>
    <h2>Item 9 — US DOT Description</h2>
    {row("9a. Waste Code(s)", e(waste.get("federal_waste_codes", "")))}
    {row("Waste description", e(waste.get("description", "")))}
    {row("9b. Containers", '<span class="missing">placeholder — not the point of this demo</span>')}
    {row("9c. Total Quantity (allocated)", e(f"{total_qty} tons") if total_qty is not None else '<span class="missing">not yet resolved</span>')}
    {row("9d. Unit", "T (tons)")}
    {row("Form Code", e(waste.get("form_code", "")))}
    {row("Report Cycle (EPA BR_REPORTING)", e(str(waste.get("report_cycle", ""))))}
  </section>

  <section>
    <h2>Item 15 — Special Handling Instructions and Additional Information</h2>
    {row("Delivery schedule (negotiated)", e(schedule_text) if schedule_text else '<span class="missing">n/a</span>')}
    {row("Disclosed constraint this schedule satisfies", e(disclosed) if disclosed else '<span class="missing">n/a</span>')}
  </section>

  <section>
    <h2>Item 16 — Generator's/Offeror's Certification</h2>
    {row("Certification", '<span class="missing">unsigned — demo document</span>')}
  </section>

  <section class="item-20">
    <h2>Item 20 — Designated Facility Owner or Operator: Certification of Receipt</h2>
    {row("Signature", '<span class="cert-blank">[ intentionally left blank ]</span>')}
    {row("Print Name", '<span class="cert-blank">[ intentionally left blank ]</span>')}
    {row("Date", '<span class="cert-blank">[ intentionally left blank ]</span>')}
  </section>
{resolution_block}
  <footer>
    Rendered by <code>agents/manifest_render.py</code> from <code>streams/{e(stream_id)}.yaml</code>.
    Generator and receiver identifiers are real EPA Envirofacts BR_REPORTING records, used here
    to demonstrate the mechanism only — the named facilities were not contacted or informed, and
    this data is already public disclosure, not a claim about their current practices.
  </footer>

</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stream_path", nargs="?", default=None,
                         help="path to a streams/*.yaml file (defaults to the one demo stream, "
                              "if there is exactly one)")
    args = parser.parse_args()

    stream_path = args.stream_path
    if stream_path is None:
        import glob
        candidates = glob.glob("streams/*.yaml")
        if len(candidates) != 1:
            sys.exit("Ambiguous: pass a stream path explicitly (multiple/zero files under streams/)")
        stream_path = candidates[0]

    stream = load_stream(stream_path)
    receivers = load_receivers()
    snapshot_rows = load_snapshot_rows()

    doc = render(stream, receivers, snapshot_rows)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"manifest-{stream['stream_id']}.html")
    with open(out_path, "w") as f:
        f.write(doc)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
