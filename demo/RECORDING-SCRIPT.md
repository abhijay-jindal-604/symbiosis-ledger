# Symbiosis Ledger — demo recording script

Target length **3:00**. Every beat below is timed, and every command is the
exact one to run. Narration is written to be read aloud verbatim at a brisk
pace (~150 wpm); it is deliberately short so the screen has room to breathe.

Two people are on this recording: **you** (driving, narrating) and
**Bhaskar** (the CODEOWNERS reviewer, who appears only as an approval on
GitHub — no camera, no voice).

---

## Before you hit record — pre-flight

Run these in order. All five must pass.

```bash
cd symbiosis-ledger
git checkout main && git pull origin main     # expect 11f150f or later
git status --porcelain                        # expect EMPTY
.venv/bin/python -m pytest tests/ -q          # expect 104 passed
grep NEGOTIATION_MODEL .env                   # expect gemini-3.5-flash-lite
.venv/bin/python demo/confirm_llm_credit.py   # expect CREDIT CONFIRMED
```

**The model line matters.** `gemini-3.5-flash` is capped at **20 requests per
day** on the free tier and that bucket is already spent. The quota is
per-model, so `.env` now pins `gemini-3.5-flash-lite`, which was verified
live to complete the full tool-calling negotiation. If you remove that line,
the on-camera run falls into its honest even-split fallback and the whole
middle of the video collapses.

**Budget your API calls.** One negotiation run costs 2–3 requests. Do not
rehearse the negotiation against the real repo — rehearse in the throwaway
clone (see *Retakes* at the bottom).

Also open and leave ready, in separate tabs:

| Tab | URL |
|---|---|
| PR list | `github.com/abhijay-jindal-604/symbiosis-ledger/pulls` |
| PR #18 | kiln-b claims AKD000850701 |
| PR #19 | wwtp-c claims AKD000850701 |
| Branch protection | Settings → Branches → `main` |
| Web viewer | `http://localhost:8765/index.html` |

Start the viewer server and leave it running:

```bash
cd web && python3 -m http.server 8765
```

**Screen setup:** terminal font ≥ 18pt, dark theme, window at ~1600×900 so
text is legible after compression. Browser zoom at 110%. Close every
notification source.

---

## Slides

Three slides only. Everything else is live. Keep them plain — white text,
dark ground, one idea each. No logos, no build animations.

### Slide 1 — the problem (on screen 0:00–0:18)

> **Symbiosis Ledger**
>
> 14,039 tons of hazardous waste in an 8,000-row EPA sample
> went to landfill or incineration.
>
> **6,839 of those shipments** had a permitted recovery facility
> whose own filing history covers every waste code on the row.

Small footer, 60% opacity: `Source: EPA Envirofacts BR_REPORTING, pulled 2026-09-12`

### Slide 2 — the mechanism (on screen 0:18–0:36)

A three-box diagram, left to right:

```
   stream = a YAML file          claim = a pull request        two claims = a MERGE CONFLICT
   in a git repo                 against that file             on the same line
```

Nothing else on the slide. This is the whole idea and it should land in one
look.

### Slide 3 — the trust close (on screen 2:30–3:00)

Three rows, revealed together (no animation):

> **31 adversarial fixtures — 0 silently wrong allocations**
> `demo/run_eval.py`, includes prompt-injection attempts inside claimant text
>
> **Every resolution is one commit — so `git bisect` finds a bad split in log₂(n) steps**
> `agents/check_allocation.sh`
>
> **The agent cannot merge its own work**
> Required CI check + CODEOWNERS review + admin bypass disabled

---

## The script

### Beat 1 · Slide 1 · 0:00 – 0:18

**Show:** Slide 1.

**Say:**

> "Every year, American industry ships millions of tons of hazardous waste to
> landfills and incinerators — while another permitted facility down the road
> is licensed to recover that exact waste code. Matching them isn't the hard
> part. The hard part is that nobody trusts the match."

---

### Beat 2 · Slide 2 · 0:18 – 0:36

**Show:** Slide 2.

**Say:**

> "So we made the ledger a git repository. Every waste stream is a YAML file.
> A facility claims a stream by opening a pull request. And when two
> facilities want the same stream — that is, literally, a merge conflict."

---

### Beat 3 · Live GitHub · 0:36 – 0:52

**Show:** The PR list, then hover #18 and #19 so both titles are readable.
Click into #18 → **Files changed** → point at the changed line.

**Say:**

> "Two real open pull requests. Kiln-B and WWTP-C both want two hundred and
> one tons of benzene-contaminated filters from a refinery in North Pole,
> Alaska — real EPA Biennial Report data. Both of them edit the same line of
> the same file."

---

### Beat 4 · Live terminal — the conflict and the negotiation · 0:52 – 1:32

**Show:** Terminal, full screen. Run:

```bash
.venv/bin/python demo/run_negotiation.py \
  --stream streams/AKD000850701-D001D018-W310-2007.yaml \
  --base-branch claim/kiln-b-north-pole \
  --other-branch claim/wwtp-c-north-pole
```

There is a real API pause of roughly 15–30 seconds between the `CONFLICT`
line and the result. **Narrate straight through it** — the constraint
explanation below is written to fill exactly that gap. Do not cut here; the
wait is the agent working and it reads as real.

**Say** — as the conflict line appears:

> "Git refuses the merge. Content conflict, same line. Now the negotiation
> agent reads what each side actually disclosed."

**Say** — over the pause:

> "Kiln-B can take ninety tons, but only in forty-five-ton truckloads, two
> weeks apart. WWTP-C will take any quantity in one pickup, but needs at
> least a hundred and fifty tons to justify sending the truck. There are two
> hundred and one tons on the table. Those two constraints cannot both be
> satisfied."

**Say** — when `RESOLVED_SPLIT` prints:

> "Ninety tons to Kiln-B, a hundred and eleven point eight to WWTP-C — and it
> states plainly that WWTP-C falls short of its own hundred-and-fifty-ton
> threshold. It doesn't round the problem away. It names the shortfall."

> **On-screen tip:** scroll up two lines so `'feasible': True` and the
> `explanation` string are both visible while you deliver that last line.

---

### Beat 5 · Live web viewer — the evidence trail · 1:32 – 1:52

**Show:** In a second terminal pane:

```bash
.venv/bin/python agents/export_viewer_data.py
```

Then switch to the browser and hard-refresh the viewer. Scroll to the
`AKD000850701-D001D018-W310-2007` card — it is now `RESOLVED_SPLIT`, with
the allocation bar and the three-step tool trace.

**Say:**

> "And it didn't take any of this on faith. It called the receipt-history
> tool on both facilities — checked against real EPA filings. Then, before
> committing, it called check-allocation on its own proposed split and
> verified the arithmetic. Two hundred one point eight three four. Every call
> and every return is logged."

---

### Beat 6 · Live GitHub — the gate · 1:52 – 2:30

**Show, in this order:**

1. `git push origin claim/kiln-b-north-pole`
2. PR #18 → the `eligibility` check spinning, then green
3. Scroll down to the **red** "Review required · Code owners" block, with the
   merge button disabled
4. *(hard cut)* Bhaskar's approval appears — review turns green
5. Click **Merge pull request**

**Cuts:** CI takes 30–60 seconds and Bhaskar's approval is out of your
hands. Make **two visible hard cuts** — at step 3→4, and while CI runs if it
drags past ~15s. A clean jump cut is honest; a silent 40-second stare is not.
Brief Bhaskar to approve the moment you message him, and stay on the PR page
so the approval lands on camera.

**Say:**

> "But nothing merges on the agent's word. I push the resolution. CI runs the
> eligibility check, which independently re-verifies both facilities against
> the EPA snapshot — green. And it's still blocked. Branch protection
> requires a code-owner review, and admin bypass is off, so I cannot merge my
> own agent's work even though I own this repository. My teammate reviews it.
> *Now* it merges."

> **Worth showing if you have the second:** flash the Settings → Branches
> page so "Do not allow bypassing the above settings" is visibly checked.
> That's the line that makes the gate real rather than decorative.

---

### Beat 7 · Slide 3 · 2:30 – 3:00

**Show:** Slide 3.

**Say:**

> "Three things make that trustworthy. The eval harness scores the agent
> against thirty-one adversarial fixtures — including prompt-injection
> attempts hidden inside the claimants' own constraint text — with zero
> silently-wrong allocations. Because every resolution is exactly one commit,
> `git bisect` finds a bad split in a handful of steps. And the agent
> structurally cannot approve itself. The waste stream isn't the ledger's
> output. The audit trail is."

---

## If you're allowed more than 3 minutes

Two inserts, in priority order.

### Insert A — the planner's memory (+25s, place after Beat 5)

This is the strongest remaining "agentic" beat: the planner ranks candidate
receivers, gets one genuinely rejected, records that, and a second
invocation produces a strictly shorter plan.

```bash
.venv/bin/python demo/run_planner.py      # run 1: 3 ranked candidates
.venv/bin/python demo/run_planner.py      # run 2: 2 candidates, one excluded with a date
```

> "The planner ranks candidate receivers by real receipt history. Recycler-D
> wins the tiebreak on its declared specialty, gets proposed — and gets
> genuinely rejected. Run it again: recycler-D is gone from the ranking, with
> the rejection date attached. It doesn't re-ask a question this system has
> already answered."

**Important:** run 1 is a one-shot. Once you run it, the rejection is on
record and you cannot re-record run 1 without resetting
`receivers/profiles/`. Rehearse this in the throwaway clone only.

### Insert B — bisect (+25s, place before Beat 7)

```bash
.venv/bin/python demo/seed_bad_commit.py
mkdir -p /tmp/bisect
cp agents/check_allocation.sh agents/validate_allocation.py agents/stream_io.py /tmp/bisect/
export BISECT_VALIDATOR=/tmp/bisect/validate_allocation.py
git bisect start demo/bisect-history main
git bisect run /tmp/bisect/check_allocation.sh
git bisect reset
```

> "Suppose an agent misreads a constraint and over-allocates. Because each
> resolution is one commit, bisect walks the history and names the exact
> commit that broke the arithmetic — then hands back the model response that
> produced it."

Run `git bisect reset` **on camera**. Leaving a repo mid-bisect is the kind
of detail a judge notices.

---

## Retakes

`demo/run_negotiation.py` **does not push**. Everything before Beat 6 is
locally reversible.

**Bad take, before you pushed:**

```bash
git checkout claim/kiln-b-north-pole
git reset --hard origin/claim/kiln-b-north-pole
git checkout main
git checkout -- web/data.json      # discard the local viewer export
```

Then re-run Beat 4. Each retake costs 2–3 API requests.

**Rehearse here, not in the real repo.** A working throwaway clone with its
own venv and `.env` already exists at:

```
/tmp/claude-1000/.../scratchpad/negdry/repo
```

It is wired to the same GitHub remote but `run_negotiation.py` never pushes,
so nothing you do there touches the real branches.

**Once Beat 6 merges, the demo is spent.** Stream 3 becomes `RESOLVED_SPLIT`
on `main` and there is no live conflict left. So: get Beats 1–5 on tape you
are happy with *before* you push. Beat 6 is the last thing you shoot.

After the merge, regenerate and commit the viewer data so the published page
reflects the new resolution:

```bash
git checkout main && git pull origin main
.venv/bin/python agents/export_viewer_data.py
git checkout -b fix/viewer-after-third-resolution
git add web/data.json && git commit -m "Refresh viewer data after the third stream's resolution"
git push origin fix/viewer-after-third-resolution
```

---

## Things not to say

- Don't call the web viewer a dashboard or a live system. It is a static
  render of committed repo state, and a judge who pokes at it will find that
  out. "A rendering of what's in the repo" is both accurate and enough.
- Don't say the corpus number is waste you *would* divert. It's the count of
  shipments where a code-compatible recovery facility existed. Eligibility is
  necessary, not sufficient — no permit, capacity, or cost check is done, and
  the README says so.
- Don't claim the agent decides anything. It proposes; CI and a human
  code-owner decide. That asymmetry is the pitch — don't trade it away for a
  stronger-sounding verb.
