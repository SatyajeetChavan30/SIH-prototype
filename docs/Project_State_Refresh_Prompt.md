# Prompt — refresh the (PROJECT NAME) state primer

Paste everything below the rule into a fresh agent session that can read the engine repo.
It rebuilds `PROJECT_STATE_PROMPT.md` — the context brief pasted at the start of a new AI
session — from the repository as it stands today. Run it whenever the primer has gone stale.

---

You are refreshing the state-of-the-project primer for (PROJECT NAME), a Smart India
Hackathon 2026 entry for Problem Statement **26161** (NTRO, Software, Disaster Management).
The primer is a briefing document: someone pastes it into a fresh AI session so that
session knows what is true about the project before it does anything. Its only virtue is
accuracy. A primer that flatters the project is worse than no primer, because everything
written from it inherits the error.

## Files

| | Path |
| --- | --- |
| **Engine repo** | `D:\pd\chosen one\SIH prototype` |
| **Progress site repo** | `D:\pd\chosen one\sih prototype progress` |
| **The primer you are rewriting** | `sih prototype progress\PROJECT_STATE_PROMPT.md` |

Read the existing primer first. Its final section says what it covered and when; everything
after that date is your subject. Keep its section structure — problem statement, what the
system is, deliverable table, measured evidence, honesty rules, what's new, documents,
contradictions, submission state, open items, how to work — unless the project has changed
shape enough to need a different one.

**The 20 September 2026 screening deadline has passed.** Do not assume the primer's old
submission section still describes the current phase. Find out what phase the project is
actually in before writing about it, and if the repo does not say, write that it does not
say rather than guessing.

## Step 1 — Work out what actually changed

**File modification times lie in this repo.** A sync or checkout has bulk-touched almost
every file to the same timestamp, so a recent mtime means nothing and an old one means
nothing either. Use these instead, in order of reliability:

1. `git log --since=<primer date> --stat` and `git diff --stat <commit>..HEAD` if you have
   a shell. This is the only complete answer — use it if you can.
2. **File sizes against the previous primer's evidence.** A doc that grew has new content
   in it; a doc whose size is unchanged has not been touched since the last refresh.
3. Files that exist now and are not mentioned anywhere in the old primer.

## Step 2 — Read the sources, and know what each one is for

Authoritative, in this order:

- **`data/runs/*.log`** — the ground truth for what a run actually did. Read the **tail** of
  each large or recent log: volume balance, verdict, final hazard counts, gauge arrivals,
  export counts, total wall clock, and the `RUN_ID=` line. Everything else about a run is
  someone's account of it.
- **`docs/validation_findings.md`** — the measurement record, organised in numbered
  sections. Every headline figure should trace to a section here.
- **`docs/DECISIONS.md`** — architecture decisions with rationale and consequences. The
  highest-numbered sections are the newest.
- **`docs/VERIFICATION_LOG.md`** — the coefficient queue. The highest-numbered row is the
  newest. This is where you learn which constants are unvetted and which published models
  exist in shape only behind a `*_VERIFIED = False` flag.
- **`CLAUDE.md`** — the working brief. Large; read its heading list first and then only the
  sections your diff points at. Good for current dashboard capability and gotchas.
- **`README.md`, `docs/progress.md`, `desktop/README.md`** — capability and packaging
  claims, and the test-suite count.

Not measurements, and never to be quoted as achievements:

- **`BUILD_STATUS.md`** states phase *targets*.
- **Any `*_PROGRESS.md` or launch record.** These are written when a run is *started*. A
  section headed "Expected Outputs" is a prediction. Check the corresponding log before
  repeating a single number from one, and if the prediction did not hold, say so in the
  contradictions section.

## Step 3 — Build a ledger, one line per figure

For every number that might go in the primer, record: the value, the file and line it came
from, and the conditions it was measured under. A figure without all three does not go in.

Conditions are not optional decoration:

- Every simulation figure carries its **study area, grid size, simulated duration and
  ensemble member count**. A speed-up carries its grid size and member count.
- **Computing time is wall-clock time. Simulated flood time is a different quantity.**
  Never let one stand for the other; never write "real-time forecast".
- A run's roughness treatment matters: a run solved with a **uniform Manning's n** rather
  than a land-cover-derived field taints every impact figure downstream of it, and the run
  summary records which it was.
- A corridor-conditioning figure is quoted with its domain and resolution, or not at all.

If two files disagree, both entries go in the ledger and the disagreement goes in the
contradictions section. Do not pick the more flattering one, and do not average them.

## Step 4 — Hunt contradictions on purpose

The last two refreshes each found several, and they are the most useful thing in the
primer. Look specifically for:

- A claim in `README.md` that the claim audit forbids. At the last refresh the README still
  said "100-member breach hydrograph ensembles" and still called SWE/SPH "coupled", and the
  repo is public.
- A launch record's figures credited to the wrong run. At the last refresh
  `RUN_5_PROGRESS.md` credited one run's drainage figures to a different run on a different
  domain at a different resolution.
- A stale section inside an otherwise current document. `VERIFICATION_LOG.md`'s Phase 1
  block still describes a central-difference solver that everything else says was replaced.
- The same identifier meaning two things. "Item #14" in `VERIFICATION_LOG.md` is the GEE
  free-tier row in the queue and the CSI/F1 benchmarks in the Phase 9 block.
- Test counts that disagree between documents.

## Step 5 — Carry the honesty rules forward, and revise them only on evidence

The claim audit of 6 September 2026 is still binding. Copy its forbidden list into the new
primer **verbatim**, except where a measurement has genuinely overtaken it — and when that
happens, rewrite the rule rather than deleting it. (Example from the last refresh: "100-member
ensemble is fabricated, real runs are 2–6 members" became "the largest real ensembles are
40 members; most runs are 2–6", because two 40-member runs completed. The rule survived; its
number moved.)

Never drop a rule because it is inconvenient, and add a new rule whenever this refresh
turns up a figure a reader could honestly misread. The last refresh added four:

- A 100 %-retained volume balance on a domain large enough that the flood front never
  reaches a boundary is **not** a drainage failure — the run log says so itself, and the
  primer must too.
- Two SPH engines are not one engine made faster. Wall clocks are comparable within an
  engine and to nothing else.
- Any impact figure inherits its run's roughness treatment.
- The unvetted-coefficient families stay labelled as such, and a published model that
  exists only in shape behind a `_VERIFIED = False` flag is not a published model in use.

Keep these exact phrasings wherever the subject comes up: the SWE → SPH handoff is
**one-way**, never "coupled"; Delft3D naming is conditional on the `delft3d_binary_used`
flag and the project is validated *against* the Delft3D FM kernel, not an implementation of
it; the Sentinel-1 work is **GRD change detection, not InSAR**; the DEM work is
**observation-conditioned burn-in, not photogrammetry**; a synthesised comparison curve is
never presented as a result.

## Step 6 — Write it

- Keep **(PROJECT NAME)** as a literal all-caps placeholder throughout. Do not hardcode the
  real name.
- Date the primer, and say which version it supersedes.
- Plain, precise prose. No marketing adjectives, no invented statistics, no rounding up.
- Where a claim is provisional, the primer says so in the sentence that makes the claim —
  not in a footnote.
- A refusal the system performs correctly (a detector that declines when it cannot verify a
  result, a GPU run refused up front rather than falling back) is **evidence of rigour and
  belongs in the primer**, not an embarrassment to bury.
- The open-items section is ordered by what is most urgent now, not by what is easiest.

## Step 7 — Verify before reporting

- Re-read the finished primer and confirm **every figure appears in your ledger** with its
  source and its conditions.
- Confirm the deliverable table's counts match its own rows.
- Confirm no number from a launch record's "expected outputs" survived into the evidence
  section.
- Confirm every forbidden claim from the audit is absent from the primer's own prose — it
  is easy to repeat one while explaining it.
- Save the primer to `sih prototype progress\PROJECT_STATE_PROMPT.md`, replacing the old
  one.

## Report

1. **What changed** since the previous primer, one line each, with the source file.
2. **New figures added**, each with the file and the conditions it was measured under.
3. **Rules revised**, old wording → new wording, and the measurement that justified it.
4. **Contradictions found**, and which file should be corrected for each.
5. **Could not verify** — anything you had to leave qualified, and what would settle it.

Do not commit or push. I will read the diff first.
