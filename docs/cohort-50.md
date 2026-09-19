# Cohort benchmark: 50 memories, 50 questions (clean run)

Run: 2026-09-19 · Hermes v0.21.3 · `deepseek-flash` · one fresh session per question

**This run supersedes two earlier attempts, both of which were invalid.** The
failures are documented below because the corrected result only means something
if the correction is visible.

## Why the first two runs were invalid

**Run A** measured agents on containers that had ~1,000 messages of my own setup
conversation in `state.db`. Questions could be answered from session history
rather than memory. I even identified this contamination in the write-up and
published the number anyway — that was the mistake, and it is worse than the
technical flaw.

**Run B** had clean containers but a broken grader: substring matching counted a
correct *refusal* as a pass whenever the answer mentioned the needle while
explaining it did not know the fact. Example:

> Q: how do I like to merge code?  A: "I don't have that recorded... nothing
> there states a merge preference."

That contains "rebase" and "merge", so it scored as a pass. It is the opposite
of recall.

Correcting to a refusal-regex then over-corrected, flagging true answers as
failures when the denial was about *additional* detail ("Conversational — you
picked it up living in Berlin. I have no formal level recorded"). Three graders
produced 42/50, 28/50 and 26/50. Tuning a grader until it produces a preferred
number is not measurement, so the final figures below come from **reading every
failing transcript** and adjudicating them individually.

## Setup

Both containers rebuilt from keeper images with:
- `state.db` deleted, `sessions/` emptied, all memories cleared
- verified **0 messages, 0 sessions, empty memdir** before anything was written
- memories installed by direct file write, not by an agent, so no session
  history is created in the process

50 distinct memories (preferences 12, background 8, environment 12, work 10,
logistics 8), verified free of near-duplicates. Then 50 plain questions, each in
a fresh session.

Native's cap accepted **28 of 50**; the other 22 were refused outright.
Dynamic stored all 50 in **5 index lines / 400 chars**.

## Result

| | native | dynamic |
|---|---|---|
| recalled | **29/50 (58%)** | **46/50 (92%)** |

Split by whether native could store the fact at all:

| native | recalled |
|---|---|
| facts that FIT the cap (28) | **28/28 (100%)** |
| facts the cap REFUSED (22) | **1/22 (5%)** |

**This is the finding.** With session history eliminated, native recalls
*everything it stored* and *almost nothing it could not store*. Its earlier
"84%" was an artefact of a contaminated database.

## Native's one fabrication

`wk_branch` — asked how branches are named, native produced a detailed
convention (`<type>/<short-slug>`, ticket id after the slash, under 50 chars)
and then admitted: *"nothing in my notes or on this box says what convention you
actually use — so the above is a recommendation, not your house style."* The
admission saves it from being a silent hallucination, but the fact was not
recalled. Worth noting because it shows the failure mode native falls into when
the cap has refused a fact.

## Dynamic's 4 failures — all routing, nothing lost

| id | question | what happened |
|---|---|---|
| `pref_shell` | what shell do I use? | answered "bash" — described the **container's own shell** instead of the stored preference |
| `pref_notes` | how do I take notes? | went to the `obsidian` skill, found no vault, never surfaced the stored preference |
| `env_terminal` | what terminal do I use? | no answer from memory |
| `lg_reading` | what do I read? | no answer from memory |

All four facts were **verified present on disk**. This is the design's predicted
weakness: the index failed to route, or the agent preferred local evidence
(the container's shell, an unrelated skill) over injected memory. Nothing is
lost — the answer is simply wrong, which is the *quieter* failure mode.

## Category breakdown

| category | native | dynamic |
|---|---|---|
| background (8) | 4/8 | 8/8 |
| environment (12) | 9/12 | 11/12 |
| preference (12) | 12/12 | 10/12 |
| work (10) | 3/10 | 10/10 |
| logistics (8) | 1/8 | 7/8 |

Native's stored categories (preference 12/12) survive perfectly; the categories
that came later in the feed are gutted.

## Limitations

1. **n=1 per question.** No repeats, no variance.
2. **Single model.** `deepseek-flash` shows a strong bias toward local filesystem
   evidence over injected memory, which likely *inflates* dynamic's failure count
   — `pref_shell` is the clearest case.
3. **Adjudication is human judgement.** The counts depend on my reading of each
   transcript. Raw answers are committed so the calls can be challenged.
4. **Synthetic facts, synthetic user.** Real memory is messier.
5. **Memories were installed by file write, not through the agent's own tool.**
   This is deliberate (creates no history) but means the write path was not
   exercised.

## What this establishes

With session history eliminated, memory is the only route to the answer, and:

- **native recalls 100% of what it can store and 5% of what it cannot.** The cap
  is not a performance limit, it is a hard information loss.
- **dynamic recalls 92%** with everything stored, and its failures are routing
  errors rather than data loss.
- **dynamic is not better at retrieval.** At 11 of 12 on preferences it is
  *worse* than native's 12/12. Its advantage is coverage, and coverage is what
  the 50-memory cohort actually measures.

## Next

- **3x repeats** — required to separate `pref_shell`-style routing failures from
  variance.
- **Fresh container per question** would be strictest, though the current design
  (fresh session, one shared memory dir) matches real usage.
- **Track when routing degrades** as the index grows past ~10 lines.
