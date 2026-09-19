# Reproduction log

Records independent re-runs of the benchmarks, including where they **disagree**
with the published numbers. A reproduction that only ever confirms is not a
reproduction.

## 2026-09-19 — complexity benchmark, full clean re-run

Rebuilt both containers from the keeper images, wiped session state, ran
`run_complexity.py` end to end from the committed fixtures.

| | published | re-run |
|---|---|---|
| native, stored facts | 11/11 | **10/11** |
| native, refused facts | 0/19 | **3/19** |
| **native total** | **11/30** | **13/30** |
| dynamic | 30/30 | **30/30** |

### Dynamic reproduced exactly

30/30, matching. The one apparent discrepancy was a **grader false-negative**: the
mechanical regex flagged the on-call answer as a denial because the text contains
"Nothing in my...", while the answer actually asserts the rule correctly:

> "After any sev-1 that ran past 4 hours, the responders get the next business day
> off — no need to ask (on-call policy, ~/.hermes/memories/c6_oncall_escalation.md)."

Read the transcript, not the regex. This is the third distinct false-negative the
mechanical grader has produced and it is why adjudication is manual.

### Native did not reproduce: 13/30 vs 11/30, and the difference is not memory

Three probes flipped from fail to pass. All three are facts native **refused**
(c3 and c6 were never in its block this run — it only stored c1 and c2). Reading
the transcripts shows where the answers came from:

- **`c3 headline`** and **`c3 roll back code, NOT migration`**: answered from the
  c1 migration policy that native *did* store, plus its own reasoning. The deploy
  ordering was reconstructed from the migration rules, not recalled. Plausible —
  and partly correct — but not the fact under test.
- **`c6 detail: CTO + auto sev-1`**: contains a correct-sounding 30-minute figure
  derived from the c2 severity policy's *exec notification* timer, which is a
  different rule. The answer explicitly says "the 30-minute figure applies to
  executive notification... not from an unanswered page" — it is reasoning its way
  to a plausible wrong answer and flagging the mismatch.

So native's real score in this re-run is **10/11 on facts it stored and 0/19 on
facts it refused** — the same shape as the original, with one stored probe missed.

### The setup flaw this exposes

The re-run leaves `cx_*.md` fixture files in the **dynamic** container, and the
native container can read the shared filesystem paths the answers cite. Worse, in
the original run two probes were answered from a stray
`examples/memories/deploy-pipeline.md`. **Anything on disk is reachable by both
agents**, so a "refused" fact can still be answered from a source other than
memory, and a naive grep-based grader will score it as recall.

**Fix for future runs:** prune every memory fixture not belonging to the instance
under test, and never score a probe as a recall success unless the fact was
verifiably in that instance's own memory. The scripts now separate stored from
refused in the results for exactly this reason — check `native_stored` before
trusting any native pass.

### What this does and does not change

- **The headline comparison holds.** Dynamic 30/30 vs native ~10-13/30. Even
  taking native's most favourable reading (13/30), the gap is large, and the
  structural finding — native stores 2 of 6 complex facts and loses the rest
  entirely — reproduced exactly.
- **The published 11/30 is a single sample.** With n=1 and observed variance of
  ±2 probes on the stored set, quote it as **"roughly 11/30, n=1"** rather than a
  precise figure. `docs/complexity.md` already lists n=1 as a limitation; this run
  quantifies it.
- **Any future run must prune before installing.** Otherwise the native number is
  inflated by cross-contamination and cannot be trusted in either direction.

### Verdict

Dynamic: **reproduced**. Native: **reproduced in shape, not in exact count**, with
the variance traced to reconstruction rather than recall. The methodology fix
(prune fixtures, gate on `native_stored`) is required before the next run.
