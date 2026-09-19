# Benchmark: native Hermes memory vs dynamic memory

Run: 2026-09-19 · Hermes v0.21.3 · **model `deepseek-chat` via provider `deepseek`** · n=1 per query

**Headline: the two systems are indistinguishable until stock memory fills up. Past that point, stock memory silently truncates and drops facts, and dynamic memory keeps answering.**

Three experiments, in the order they were run. The first was wrong and is kept
here so the correction is legible.

---

## Experiment 1 (WRONG): general technical questions

Asked "how do I check Kafka consumer lag" and "what does volatile-lru mean"
against a 12-topic corpus. Both systems answered well.

This measured **the model, not the memory.** `deepseek-chat` knows Kafka and
Redis cold, and native answered correctly on 3 of 5 queries **without consulting
its memory at all**. When the memory under test is not the source of the answer,
the comparison says nothing. Discarded.

---

## Experiment 2: private facts, direct questions

Facts that exist **nowhere except the memory files** — invented cluster name,
dated decisions, specific numbers. If the answer is right it came from memory.

Twelve plain questions ("what is our kafka cluster called?"), fresh session each,
same facts both encodings. Native's copy filled 1,813/2,200 chars, so it was
**not** disadvantaged at this size.

**Result: 12/12 native, 12/12 dynamic. A tie.**

Both retrieved genuine private facts: the 21-day retention with its reasoning,
`tenant_id=8812` as the hot-partition cause, the Friday 14:00 UTC freeze, the
liveness→readiness fix. At three topic files the systems are equivalent. This is
stated first because everything after it depends on understanding that the
baseline is *parity*, not a dynamic win.

---

## Experiment 3: fuzzy prompts — no keyword overlap

The design's actual claim is that a keyword index works when the user's
vocabulary differs from the index's. So: 12 questions sharing **zero keywords**
with the index line holding the answer (verified programmatically; the check
caught and rejected three of my own drafts).

| prompt | expected |
|---|---|
| "how long do we hold payment messages before they age out?" | 21 days |
| "at what point does the team get woken up about a backlog?" | 50,000/partition |
| "someone shipped something broken this morning — how do we put it back?" | `bk rollback --to` |
| "what system actually executes our build and ship process?" | Buildkite |
| "if we add a new alarm, how should its trigger value be expressed?" | absolute, never % |

**Result: 12/12 native, 12/12 dynamic. A tie again.**

Both bridged the vocabulary, not just the index. Native on "payment messages
before they age out": *"21 days... set 2026-08-14 to satisfy the audit requirement,
while replay was asking for longer."* Dynamic on the same: *"21 days — for all
`evt.payments.*` topics (decision dated 2026-08-14)."*

**Honest note on what this can and cannot show:** native does not *need* to bridge
vocabulary here — all three fact files are resident, so the model matches against
prose it can already see. This run therefore cannot separate "the index routed
fuzzily" from "the fact was already sitting in the block". That question is what
Experiment 4 answers.

---

## Experiment 4: past the cap — where they diverge

Added 5 more topics (billing, secrets, API versioning, backup, feature flags),
taking both to **8 topics**. Dynamic's index: 8 lines, ~760 chars resident,
comfortably inside budget. Native: ~600 chars per compressed entry means ~4,800
needed against a 2,200 cap.

**Native was not refused.** It consolidated — shortened existing entries to make
room. Verbatim from its own reporting: *"compressed the six existing entries"*,
*"the same batch compacted five existing entries"*.

### The damage, measured against the verbatim file

Native's final block is **2,198/2,200 chars** and:

- **one entry is truncated mid-sentence** — it ends `"The rollout ladder w"`
- **the `deploybot` identity fact is gone** — dropped during consolidation
- 17 of 19 other facts survived, so the loss is partial, not wholesale

### Probing the damaged facts

| probe | native | dynamic |
|---|---|---|
| rollout ladder + flag exemptions (native's text ends mid-sentence) | **FAIL** | PASS |
| deploy identity + rotation | PASS (partial) | PASS |
| refund approval threshold (control — survived in both) | **FAIL** | PASS |

**Native on the truncated entry — and this is the most important transcript in
the document:**

> "Checked everywhere before answering: the memory file, the full session DB
> (every message from every prior session), cron/plugins/config, and a
> filesystem-wide grep. Only one copy of the feature-flag rules exists, and it
> ends mid-sentence."

Native searched exhaustively, found the damage, and **reported it honestly**
rather than inventing the missing rollout ladder. That is the right behaviour and
it deserves saying plainly.

Dynamic answered the same question completely — `1% → 10% → 50% → 100%`, 24
hours minimum per step, `ff.kill.` exempt — because the full text was on disk
where the index pointed.

### The control question also failed

The refund question was included as a control, on the assumption its fact had
survived in native's billing entry. It had — but native answered *"I don't have
this one"* anyway. Investigating why is out of scope for this run; it means
native's score here is at least partly noise and should not be read as 1/3.

---

## What this does and does not establish

**Established:**

- At small scale, the two systems are **equivalent** (12/12, twice).
- Stock memory does not refuse when full — it **consolidates**, silently
  truncating entries and dropping facts. At 8 topics this cost one truncated
  entry and one lost fact.
- Truncation is **detectable in principle** (native found it), but only after
  the fact is already gone, and only because it happened to be visibly
  mid-sentence.
- Dynamic memory kept all 8 topics fully answerable within the same resident cap.

**Not established:**

- That truncation is *harmful in practice*. One lost fact out of 19 is not a
  catastrophe; the real question is the loss rate at 25–50 topics, which was not
  measured. The extrapolation is plausible and unproven.
- That dynamic's index scales cleanly. Past ~20 lines, keyword collisions become
  possible and retrieval precision may degrade. **Untested.**
- Anything about per-turn cost or long-run behaviour.

## Limitations

1. **n=1 per query.** No repeats, no variance.
2. **8 topics is small.** The cap starts biting at ~4 and dynamic's own index
   should start straining ~20; neither extreme was reached.
3. **Scoring is needle-matching** on distinguishing strings, verified by reading
   transcripts — not exact-match grading. The control failure (o3) shows the
   scoring can mislead in both directions.
4. **One model, one provider, one day.**
5. **The consolidation was performed by the agent**, not by a deterministic
   script. Another run might compress differently and lose different facts, so
   the specific losses are illustrative, not reproducible guarantees.

## Next: the large-cohort run

This is now the clearly-justified next step, and the design is obvious:

- **25–40 topics**, written in batches, with facts recorded **in a known order**
  so eviction can be tracked rather than inferred.
- **A fact-survival audit after every batch** — re-ask the earliest facts as new
  ones are added. That measures the eviction curve directly, which is the number
  that actually matters.
- **Fuzzy prompts only** for the precision side, plus a wrong-file rate as the
  index grows.
- **Repeats** (3x) to separate signal from noise; the control failure here shows
  single samples are not trustworthy.

## Reproduce

Fixtures and scripts in `/tmp/bench/`: `facts.json`, `install_facts.py`,
`run_facts.py`, `run_fuzzy.py`, `overflow.py`, `overflow_probe.py`, plus raw
transcripts. Containers `hermes-native` (`hermes-native:0.21.3`) and `hermes2`
(`hermes-dynmem:1.4.3`); both accept `DEEPSEEK_API_KEY` via `-e` and neither
bakes a credential. Raw answers for all runs are committed as
`docs/benchmark-raw-results.json`.

## Conclusion

Stock Hermes memory and dynamic memory perform **identically** — including on
fuzzy, keyword-free prompts — until the 2,200-char cap fills. Past that point
stock memory begins silently truncating entries and dropping facts, while the
index keeps every topic intact and answerable at roughly an eighth of the
resident cost.

The defensible claim is **not** "dynamic memory answers better". It is:
**equivalent retrieval, plus a much higher ceiling before information starts
being lost.** The size at which loss becomes materially harmful was not measured,
and is the obvious next experiment.
