# Benchmark: native Hermes memory vs dynamic memory

Run: 2026-09-19 · Hermes v0.21.3 · model `deepseek-flash` · n=1 per query

**Headline: at small scale, both systems retrieve private facts perfectly (12/12 each). The difference is capacity and detail depth, not accuracy.**

This document supersedes an earlier version that asked questions the model could
already answer from pretraining. That was a broken experiment — it measured the
model, not the memory. Both runs are described below so the correction is legible.

## The experiment that was wrong

The first pass used general technical questions ("how do I check Kafka consumer
lag", "what does volatile-lru mean") against a 12-topic corpus. Both systems
answered well, which looked like a null result.

It was worse than null: it was **uninformative**. `deepseek-flash` knows Kafka,
Redis, and Kubernetes cold. Native answered correctly on three of five queries
**without consulting its memory at all**. When the memory being tested is not the
source of the answer, the comparison says nothing.

## The corrected experiment

Facts that exist **nowhere except the memory files** — invented cluster names,
dated decisions, specific numbers, incident details. If the answer is right, it
came from memory. If memory is missing it, no amount of pretraining helps.

Twelve questions, asked plainly ("what is our kafka cluster called?"), answered
by both agents in a fresh session. Same facts, two encodings:

- **native** — the facts crammed into the shipped **2,200-char** resident cap
  (1,813/2,200 used, so native is *not* disadvantaged at this size).
- **dynamic** — the same facts as topic files on disk, with a 3-line keyword
  index (285 chars) resident.

### Result: 12/12 both

| | native | dynamic |
|---|---|---|
| correct answers | **12/12** | **12/12** |

Both retrieved genuine private facts, not guesses. Native on retention:

> "The number came out of the 2026-08-14 decision: audit needs 21 days of
> payment events, and replay wanted longer — 21 was the compromise."

Dynamic on the same question:

> "21 days, set per-topic on every `evt.payments.*` topic... Decision dated
> 2026-08-14, cluster `atlas-events`."

Both correct, including `tenant_id=8812` (the hot-partition cause), the Friday
14:00 UTC freeze window, and the liveness→readiness fix from the Sept 14 incident.

**At three topic files, dynamic memory is not better. It is equal.** Any claim
beyond that is not supported by this run.

## Where they actually diverge: capacity

Both encodings are bounded by the same 2,200-char resident cap. They spend it
very differently:

| | cost per topic, resident |
|---|---|
| native fact entry (compressed, all detail resident) | ~600 chars |
| dynamic index line (detail on disk) | ~95 chars |

| topics | dynamic resident | native resident |
|---|---|---|
| 3 | 285 chars | 1,800 chars |
| 5 | 475 chars | 3,000 chars **OVER** |
| 10 | 950 chars | **OVER** |
| 23 | 2,185 chars | **OVER** |
| 30 | **OVER** | **OVER** |

**Native holds ~3 topics before the cap refuses new writes. Dynamic holds ~23
— about 7.7x — and at 23 topics it still has roughly 27,600 chars of detail on
disk reachable on demand, against native's ~1,800 chars total.**

This is the honest core of the comparison: not that dynamic answers better, but
that native stops accepting information at a handful of topics while dynamic
keeps the full detail for ~8x as many.

### The two failure modes are not equivalent

- **Native's ceiling is a hard, visible wall.** The tool refuses the write and
  says "consolidate now". The user knows they are out of room and chooses what
  to drop. Data loss is *the user's decision*, made with full information.
- **Dynamic's ceiling is soft and quieter.** As the index grows past roughly 20
  lines, keyword collisions become possible and retrieval precision degrades.
  Nothing errors. The failure surfaces as a wrong-file read or a missed memory.

Neither ceiling was tested here — the 12/12 run had only 3 topic files. Stating
which failure mode is preferable at 25+ topics would be speculation.

## Resident cost (measured)

`hermes prompt-size`, exact, no provider call:

| | native | dynamic |
|---|---|---|
| memory block | 2,548 B (~800 tok) | 1,236 B (~320 tok) |
| ratio | — | **2.06x smaller** |

(from the 12-topic corpus run; the 3-file fact corpus is smaller for both)

Caveat: this is the *memory block*, not the whole prompt. Dynamic's total system
prompt is slightly larger because it also loads the dynamic-memory skill, which
native has no counterpart for. The correct claim is "smaller resident memory
block carrying more content", not "cheaper prompt".

## Limitations

1. **n=1 per query.** No repeats, no variance measured.
2. **Small corpus.** 3 fact files, 12 questions. The scaling table is modelled
   from measured per-topic costs, not from an actual 23-topic run.
3. **Scoring is needle-matching** on distinguishing strings (cluster name,
   tenant ID, dates) verified by reading the transcripts — not exact-match grading.
   Raw transcripts are committed for audit.
4. **One model, one provider, one day.**
5. **No retrieval traces.** The answers cite sources (`/root/.hermes/memories/kafka-ops.md`)
   but per-query tool-call traces were not captured. `scripts/test_retrieval.py`
   does this properly and should be wired into future runs.
6. **The scaling table assumes constant per-topic cost**, which holds for the
   index but understates native's difficulty — native entries also get *harder*
   to compress as they accumulate, so its real ceiling is likely below 3.

## What would settle it

- **Run the scale test for real:** 25 topics, 40+ questions, both systems.
  Measure precision and the wrong-file rate, not just hit rate.
- **Tool-call traces** per query, so retrieval vs. reconstruction is provable.
- **Repeats** (3–5x per query) to report variance.
- **A recall test:** facts written weeks apart, then queried, to see whether
  native's earlier evictions actually cost it answers in practice.

## Reproduce

Fixtures and scripts: `/tmp/bench/` (`facts.json`, `install_facts.py`,
`run_facts.py`, `scale.py`, raw transcripts in `facts_results/`).
Containers: `hermes-native` (`hermes-native:0.21.3`), `hermes2`
(`hermes-dynmem:1.4.3`). Both accept `DEEPSEEK_API_KEY` via `-e`; neither bakes
a credential.

## Conclusion

- **Retrieval accuracy at small scale: equal.** 12/12 both. Do not claim
  otherwise.
- **Resident cost: dynamic is 2.06x smaller** for the same content, and carries
  a detail tier stock memory lacks entirely.
- **Capacity: roughly 7.7x more topics** before the cap bites, with detail depth
  unavailable to native at any scale.
- **Untested:** the 25+ topic regime where dynamic's own index could start
  losing precision, and whether native's forced consolidation costs real
  answers over time.

The defensible claim is: **dynamic memory stores and reaches substantially more
per resident byte, and does not stop accepting information after a handful of
topics.** It is not a claim about smarter answers.
