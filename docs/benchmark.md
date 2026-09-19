# Benchmark: native Hermes memory vs dynamic memory

**Status: the benchmark did not support the expected conclusion. Read the limitations before citing any number here.**

Run: 2026-09-19 · Hermes v0.21.3 · model `deepseek-flash` (deepseek-chat) · n=1 per query

## What was compared

Identical content, two encodings, two containers built from keeper images:

- **native** — stock Hermes. `MEMORY.md` filled to the shipped **2,200-char** cap
  (`cli-config.yaml.example:942`), which is what the tool allows, as it would
  look after a week of use.
- **dynamic** — memory-shaper 1.4.3 + dynamic-memory skill. The same 12 topics
  as verbose files on disk (~15.8 KB total) plus a keyword index in the resident
  block.

12 neutral technical topics: kafka, postgres, nginx, redis, docker, python, git,
terraform, rust, prometheus, bash, kubernetes.

## Result 1: the resident-cost comparison holds up

`hermes prompt-size`, exact measurement, no provider call:

| | native | dynamic |
|---|---|---|
| topics stored | 11 of 12 | **12 of 12** |
| topics retrievable in detail | 0 (no detail tier) | **12** |
| resident memory block | 2,548 B | **1,236 B** |
| resident ~tokens | ~800 | **~320** |
| detail reachable | 0 | **15,834 chars** |

The memory block is **2.06x smaller** for dynamic, and it carries all 12 topics
where native could only fit 11.

**Honest caveat:** dynamic's *total* system prompt is slightly **larger**
(18,893 vs 20,109 chars is native's advantage — dynamic's is smaller overall
here only because of differing skill indexes; in a controlled pair it also
carries the dynamic-memory skill, which native has no counterpart for). This is
not a "cheaper prompt" result. It is a "more content per resident byte, plus a
detail tier that native lacks entirely" result.

Also note the 2,200-char cap forced **one topic to be refused outright** — the
kubernetes one, which contains the liveness/readiness distinction. That is the
cap working as designed, and it is the strongest concrete argument in this
document: at 12 topics, stock memory starts *losing* information.

## Result 2: retrieval — no clear win

| # | Test | native | dynamic |
|---|---|---|---|
| q1 | exact keyword ("how do I check consumer lag") | good answer, but **did not read notes** | good answer, read `kafka-ops.md` |
| q2 | related, NOT a keyword ("consumers never catch up") | good answer, **did not read notes** | good answer, read `kafka-ops.md` |
| q3 | topic the cap refused (k8s probes) | **correct and detailed** — but from the model's own knowledge, not memory | correct, from the notes |
| q4 | fine detail (offsets retention default) | correct | correct, cited notes |
| q5 | native-favoured (volatile-lru) | correct | correct, cited notes |

**The mechanism result is the interesting one.** native answered correctly
*without consulting its memory at all* — it answered from the model's pretrained
knowledge. So did dynamic on q3, which suggests the topic file was not reached
there either.

This means the answer-quality comparison is **not measuring memory at all** on
several queries. A capable model already knows what `volatile-lru` means, so
native having it in a 2,200-char block proves nothing about retrieval.

## Limitations — why this is not evidence of superiority

1. **n=1 per query.** No repeats, no variance. A single flip in any answer
   changes the table.
2. **The model is too strong for the test.** `deepseek-flash` knows Kafka,
   Redis, and Kubernetes cold. To measure *memory*, the queries must be about
   facts the model cannot already know — private data, project-specific
   conventions, decisions made weeks ago. That is the correct next experiment
   and this run does not substitute for it.
3. **No transcript-level verification of retrieval for every query.** The
   "refs-notes" flags are keyword heuristics over the answer text, not tool-call
   traces. `scripts/test_retrieval.py` gives a real answer and was only run on
   the benchmark's smoke tests, not per query.
4. **Corpus chosen by us.** A skeptic can argue the topics were picked to favour
   keyword indexing. The 12 were chosen for realism, but that is our judgement.
5. **One model, one provider, one day.**

## What would make this credible

- Queries about **private/invented facts** the model cannot know: "what did we
  decide about the staging rollout on the 12th", "what's the retention number we
  agreed for the audit log". Answers must come from memory or not at all.
- **Tool-call traces** per query, via `test_retrieval.py`, not answer-text
  heuristics.
- **Repeat each query 3–5x** and report agreement.
- Test the **scale regime** the design is actually for: 50–200 topics. At 12
  topics both approaches cope; the cap only starts biting at ~10.
- A **weaker model** run, where pretrained knowledge can't paper over a missing
  detail tier.

## Reproduce

Fixtures: `/tmp/bench/` (corpus, encoder, installer, query runner, raw
transcripts). Containers: `hermes-native` (`hermes-native:0.21.3`), `hermes2`
(`hermes-dynmem:1.4.3`). Both take `DEEPSEEK_API_KEY` via `-e`; neither bakes a
credential.

## Conclusion

Supported: the **resident-cost** and **coverage** claims — 2.06x smaller memory
block, 12/12 vs 11/12 topics, and a detail tier native does not have.

Not supported: any claim that dynamic memory produces **better answers** on
general technical questions. On this corpus, with this model, the answers were
comparable, and several were answered from pretrained knowledge rather than from
memory at all.

The honest framing is: dynamic memory stores and reaches far more per resident
byte, and stock memory actively loses content at ~12 topics. Whether that
translates into better answers depends on the questions being about things the
model does not already know — which this run did not test.
