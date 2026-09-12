# Symbiosis Ledger

**What this is:** a demo of an industrial byproduct exchange where two real
facilities file conflicting GitHub PR claims on the same waste stream, a
required CI check verifies each claimant's eligibility against real EPA
receipt history, and an LLM negotiation agent reads each claimant's free-text
disclosed constraint (never comparable by a `WHERE` clause) and resolves the
conflict with a concrete allocation — recorded as a git commit a
CODEOWNERS-required human approval had to sign off before it could merge.

**The demo moment:** two branches edit the same stream file's `status:` line
to different values from the same base commit, producing a real, git-native
merge conflict on a real GitHub PR pair. The negotiation agent reads both
sides' disclosed constraints, computes a split (or explains why no full split
is feasible), and writes the resolved file — then that resolution has to
clear the same eligibility gate and the same human CODEOWNERS review as any
other change before `main` will accept it.

## The insight

Matching a waste stream to a facility that can legally and physically receive
it is a database lookup — that's `agents/eligibility_check.py`, a required CI
check, not agentic reasoning, and the project does not pretend otherwise.
What a lookup cannot do is arbitrate between two *eligible* claimants who each
disclose a real-world constraint in free text — "needs 15 t/week continuous"
versus "only Tue/Thu intake windows" are not fields a `WHERE` clause can
compare. Extracting the quantitative and scheduling content from each,
checking compatibility, and producing (or honestly refusing) a numeric split
requires language understanding plus arithmetic reasoning over information
that never existed anywhere in the EPA dataset. `agents/negotiation_agent.py`
— the actual "one hard thing" this project builds — is not a single blind
prompt: the model runs a real tool-calling loop, able to call
`lookup_receipt_history` to see each claimant's real EPA receipt history
for itself rather than take eligibility on faith, `get_receiver_profile` to
check that claimant's own memory (CONTEXT-DUMP §8) before repeating a
settled decision, and `check_allocation` to self-verify its own proposed
split's arithmetic before committing to a final answer. Everything else
(the CI gate, CODEOWNERS, the merge conflict itself) is real GitHub/git
mechanics used honestly, not AI theater built on top of them.

## What this deliberately does not do

- **Nothing here is transmitted to a real facility.** The rendered manifest
  (`out/manifest-<stream_id>.html`) leaves Item 20 (designated facility
  certification of receipt) visibly blank and is captioned "Generated for
  demonstration. Not transmitted to any real facility." No EPA system, no
  named facility, and no regulator is contacted by anything in this repo.
- **Eligibility is inferred, not authoritative.** EPA Envirofacts has no
  permit-based eligibility table (`HD_HANDLER`, `HD_PERMIT_WASTE_CODE`, and
  related endpoints all 404 — confirmed, not assumed). `eligibility_check.py`
  infers eligibility from a receiver's *observed receipt history* of the same
  federal waste code under a recovery-type management category, and prints
  "by waste code" so its message doesn't overstate a stronger guarantee (e.g.
  a form-code match) than what it actually checked.
- **Two GitHub identities represent two facilities, not two independent
  companies.** The team controls both accounts used as the conflicting
  claimants and the CODEOWNERS approver. This is a build-time simplification
  for a two-person team within a hackathon window, not a claim of
  independent real-world adoption.
- **The on-screen facility identifiers are real, public EPA-published
  records**, used here only to demonstrate the mechanism with real data
  rather than invented placeholders. Those real facilities (Pollution Control
  Industries Inc, Burlington Environmental LLC, Clean Harbors Environmental
  Services Inc, USAF Elmendorf AFB) were **not contacted or informed**, and
  everything shown is already public federal disclosure (RCRA Biennial
  Report data) — not a claim about any of their current practices or
  willingness to participate.

## Verify it yourself, in three commands

```bash
# (a) Re-pull the exact demo row live from EPA Envirofacts and compare it
# against the committed snapshot — no API key needed.
python demo/live_query.py
# -> prints the live row and the snapshot row side by side, then MATCH

# (b) Install and run the test suite.
pip install -r requirements.txt && pytest

# (c) Watch the eligibility gate deny a real receiver with no recovery
# history for this waste code — the same check that runs in CI. recycler-d's
# denial-evidence claim was deliberately never merged into any stream file
# on main (see PR #3), so --stream must be given explicitly here rather
# than relying on claims: auto-discovery, which has nothing to find it in.
python agents/eligibility_check.py --claimant recycler-d --stream streams/AK8570028649-D009-W301-2001.yaml
# -> ELIGIBILITY DENIED — receiver NED981723513 has 0 recorded receipts ...
```

A fourth, optional command shows the memory beat directly (see "Memory and
the recovery beat" below):

```bash
python demo/rerun_with_memory.py
# -> run 1 denies recycler-d and logs it; run 2 skips it from memory alone
```

No API key is required for any of the three commands above. A key is only
needed to re-run `agents/negotiation_agent.py` itself (see below).

## Where to look in this repo

| Artifact | Where |
|---|---|
| Conflicting claim PRs | [#1 kiln-b](https://github.com/abhijay-jindal-604/symbiosis-ledger/pull/1) (merged), [#2 wwtp-c](https://github.com/abhijay-jindal-604/symbiosis-ledger/pull/2) (auto-merged with #1) |
| Denial-evidence PR | [#3 recycler-d](https://github.com/abhijay-jindal-604/symbiosis-ledger/pull/3) — genuine red X on the eligibility check |
| Resolution commit | `197ea9a` on `claim/kiln-b`, carried into `main` at `59d6c1a` |
| Negotiation log (raw prompt + raw model response) | `logs/negotiation/AK8570028649-D009-W301-2001-20260912T081951Z.json` |
| CI run showing the denial | see PR #3's Actions tab |
| Rendered demo manifest | `out/manifest-AK8570028649-D009-W301-2001.html` |
| Bisect-history branch (seeded bug for the recovery beat) | `demo/bisect-history`, seeded bad commit `d714804` — never on `main` |
| Receiver memory profiles | `receivers/profiles/<receiver_id>.json`, written by `agents/orchestrate.py` |
| **Second demo stream** (real EPA data, resolved by the tool-calling agent) | claim PRs [#9 kiln-b](https://github.com/abhijay-jindal-604/symbiosis-ledger/pull/9) / [#10 wwtp-c](https://github.com/abhijay-jindal-604/symbiosis-ledger/pull/10); resolution commit `3c0c9a1`; log `logs/negotiation/ALD000622464-D009-W403-2009-20260912T095400Z.json`; manifests `out/manifest-ALD000622464-D009-W403-2009-kiln-b.html` and `...-wwtp-c.html` (two files: a genuine 2-way split needs two shipments) |

## Memory and the recovery beat

**Memory:** `agents/orchestrate.py` is the layer that decides *who to
propose* for a stream, and it consults each receiver's own profile file in
`receivers/profiles/<receiver_id>.json` before ever touching the eligibility
snapshot again. `demo/rerun_with_memory.py` runs the same ineligible-claimant
scenario twice: the first run denies `recycler-d` and logs the rejection;
the second run reads that file and skips re-proposing `recycler-d` entirely,
printing exactly which prior record caused the skip
(`skipping recycler-d — prior rejection recorded ...`). This is the
orchestration layer, not the CI eligibility check — the CI check stays
stateless per-PR by design; memory lives one layer up. Profile writes are
append-only and idempotent, so re-running never duplicates an entry.

**Recovery (git bisect):** `agents/validate_allocation.py` is a pure
allocation validator (0 = good, 1 = a genuine arithmetic violation, ≥2 =
untestable — never conflate a missing file or an unresolved stream with a
bad allocation). `agents/check_allocation.sh` wraps it as a `git bisect run`
predicate, mapping "untestable" to bisect's own skip code (125) so a commit
that predates the stream file is never confidently misreported as bad. The
recovery beat's setup — one deliberately over-allocated commit simulating a
misread constraint — lives only on `demo/bisect-history`, never on `main`.
Rehearsed end-to-end during this build: `git bisect run` correctly named
`d714804` (the seeded commit) as the first bad commit against parent
`59d6c1a` (the real, valid resolution on `main`), then `git bisect reset`
returned the repo to a clean `main`.

## A second real stream, and the tool-calling agent proven live

The negotiation agent was later upgraded from a single blind prompt to a
real tool-calling loop (`lookup_receipt_history`, `get_receiver_profile`,
`check_allocation` — see "The insight" above). The first stream's merged
resolution predates that upgrade, so a second real stream was added
specifically to run the upgraded agent for real: generator `ALD000622464`
("CHEMICAL WASTE MANGEMENT" — a real, verbatim EPA typo), Emelle AL,
`48.0135` tons of `D009` via `INCINERATION`, report cycle 2009. `kiln-b`
and `wwtp-c` already had real, verified `D009` METALS RECOVERY receipts in
the committed snapshot, so both are genuinely eligible for this stream too
— no new receiver identities needed.

Disclosed constraints were designed to admit a genuine full split this
time (one-time-delivery capacity caps, rather than stream 1's "needs
continuous weekly supply" framing that made a full split impossible) —
giving evidence of both outcomes in the `status`/`resolution.method` table,
not just the partial one. The agent resolved it as a real `RESOLVED_SPLIT`
on its first attempt, and its logged tool calls are the first real evidence
the tool-calling upgrade actually works against a live model:

1. `get_receiver_profile("kiln-b")` and `get_receiver_profile("wwtp-c")` —
   checked each claimant's memory before proposing anything.
2. `check_allocation({"kiln-b": 20, "wwtp-c": 28.0135})` — self-verified its
   own proposed split (sums to exactly `48.0135`) before committing to it
   as the final answer.

Getting a real Gemini call working with tools surfaced two genuine bugs,
both fixed and both worth knowing about if re-running this: Gemini 3.5
requires an opaque `thought_signature` to be echoed back on a
reconstructed function-call turn (undocumented in the SDK's own examples,
which all reuse the raw response object rather than reconstructing it —
see `agents/llm_gemini.py`'s docstring), and the free API tier's 5
requests/minute limit needs a real backoff (`api_backoff=(60, 60)` in
`demo/run_negotiation.py`) for a multi-tool-call negotiation to clear it.
Because a genuine 2-way split can't be represented by one EPA manifest
(one shipment, one designated facility), `agents/manifest_render.py` now
renders one manifest per positively-allocated claimant for a
multi-recipient resolution — `out/manifest-<stream_id>-<claimant>.html` —
rather than one file that would otherwise silently drop every recipient
but the first.

## A second negotiation protocol: two calls, blind to each other

`negotiate()` runs one call that sees both claimants' disclosed constraints
at once — convenient, but not how two real counterparties would negotiate
through a neutral arbiter: neither would normally hand its constraint
straight to the other side's reasoning process. `negotiate_blind()`
(`agents/negotiation_agent.py`) instead runs two independent calls, one per
claimant, each seeing only its own request, its own disclosed constraint,
and the stream's shared public facts — never the other claimant's name,
request, or constraint text. If the two blind proposals don't fit within
the tons available, each side gets exactly one revision round, told only
the numeric shortfall, never who the other claimant is. If they still don't
fit, the reconciliation is a deterministic proportional scale-down, never a
coin flip or an arbitrary pick of one side over the other.

Run for real against the same second-stream disclosed constraints already
used above (`demo/compare_negotiation_protocols.py`, read-only — it never
touches `streams/*.yaml` or commits anything, since those files already
carry the real, CODEOWNERS-approved `negotiate()` resolution and that audit
trail shouldn't be rewritten by a comparison run), the two protocols landed
on genuinely different splits:

| Protocol | kiln-b | wwtp-c | Unclaimed |
|---|---|---|---|
| `negotiate()` (single call, sees both sides) | 20.0 | 28.0135 | 0 |
| `negotiate_blind()` (two calls, blind) | 20.0 | 25.0 | 3.0135 |

Both splits are valid and honest given what each protocol's model call
actually knew. The single call saw that 28.0135 tons were left over after
kiln-b's 20-ton cap and handed all of it to wwtp-c. Blind wwtp-c never
learned there was slack beyond its own logistical floor of 25 tons — only
that the two initial requests exceeded the 48.0135 available by 20 tons —
so it reduced to exactly its own stated minimum and stopped there, honestly
leaving the remainder unclaimed rather than guessing at a number it had no
basis for. That gap is the real, load-bearing trade-off of negotiating
blind: it protects each side from disclosing to the other, but a genuine
arbiter with full visibility can find value blind negotiation structurally
cannot see. Logged verbatim, tool calls and all, in
`logs/negotiation-compare/`.

Getting this working for real surfaced two more genuine bugs, on top of the
two documented above: the python-genai docs' own example wraps a function
response in `Content(role="tool", ...)`, and `gemini-3.5-flash` accepts
that, but `gemini-3.6-flash`/`3.7-flash`/`3.8-flash` all reject it outright
("Role 'tool' is not supported") — `agents/llm_gemini.py` now uses `"user"`
instead, which every version accepts. Separately, `-lite` models
(`gemini-3.5-flash-lite`) reject `thinking_config` outright with a bare 400
and no further detail, apparently having no thinking mode to budget at all
— `llm_gemini.py` now skips that config key for any model with `"lite"` in
its name. Both were found the same way everything else in this project was:
by actually running it against the real API, not by guessing at the SDK's
shape.

## On reproducibility and the LLM

Re-running `agents/negotiation_agent.py` will produce a *differently worded*,
and possibly differently-split, resolution — the model is not deterministic
even at temperature 0. What's reproducible is the mechanism and the record:
the committed `logs/negotiation/*.json` file holds the verbatim prompt and
raw response for the resolution actually shown in the video, which is the
auditable claim. A judge's independent re-run producing a different split is
expected, not a discrepancy.

The resolution actually committed (`RESOLVED_PARTIAL`) was **not** a full
even split — the model determined kiln-b's disclosed "15 t/week continuous"
need cannot be met by wwtp-c's one-time 24.1325-ton batch, so it allocated
the full batch to wwtp-c and 0 to kiln-b, naming the shortfall. This is a
legitimate negotiated outcome per the `status`/`resolution.method`
vocabulary below, not a failure that was retried away.

**Note on the agent's history:** the committed resolution above and its
log were produced by an earlier, single-call version of the agent (one
prompt containing both claimants' full context, no tool calls). The agent
was since upgraded to a real tool-calling loop — it can call
`lookup_receipt_history`, `get_receiver_profile`, and `check_allocation`
mid-negotiation rather than being handed every fact pre-digested — without
re-litigating that resolution. A fresh run against a new stream will show
`tool_calls` entries inside its `logs/negotiation/*.json` attempts; the
historical log above predates that capability and legitimately has none.

`status` / `resolution.method` are a controlled vocabulary so the repo can't
overstate what produced a resolution:

| `status` | `resolution.method` | Meaning |
|---|---|---|
| `RESOLVED_SPLIT` | `negotiated_split` | Model found a split satisfying both constraints |
| `RESOLVED_PARTIAL` | `negotiated_partial` | Model found no full split, but a valid largest-feasible allocation — **this is what the demo shows** |
| `RESOLVED_EVEN_SPLIT_FALLBACK` | `deterministic_fallback` | The model path failed after retry; a plain arithmetic even split, not a reasoning result |
| `UNRESOLVED` | `null` | Even the fallback couldn't produce a valid allocation |

## Snapshot provenance

`data/br_reporting_snapshot.json` was pulled 2026-09-12 via
`https://data.epa.gov/efservice/BR_REPORTING/rows/{start}:{end}/JSON`,
paginated across rows 0–6000 (6 rows retained: the demo generator/receiver
pairs plus supporting context rows). CI reads this committed snapshot rather
than calling EPA live, for reliability and so CI doesn't hammer a government
endpoint on every run. `demo/live_query.py` is the one live call in this
repo, shown on camera, and it prints a MATCH/DIFFER verdict against this
same snapshot so the "real data" claim is independently checkable.

## Who built what

Built by Abhijay Jindal (`abhijay-jindal-604`) and Bhaskar Kumar Arya
(`Bhaskar-kumar-arya`) for this hackathon.

## AI-assisted development

Parts of this codebase were written with AI assistance (Claude). That
assistance is a tool used by the human team, the same as an IDE or a linter —
**no AI system is a contributor, author, or team member on this project.**
Commit authorship, `CODEOWNERS`, git identities, and this section name only
the real people on the team. No commit in this repository's history carries
an AI co-author trailer, and none should be added going forward.

## License

Code in this repository is MIT-licensed (see `LICENSE`). EPA RCRA Biennial
Report data is US federal public domain.

## Demo video

*Link lands here once recorded (Phase 7/8).*
