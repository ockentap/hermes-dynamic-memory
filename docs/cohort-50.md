# Cohort benchmark: 50 memories, 50 questions

Run: 2026-09-19 · Hermes v0.21.3 · `deepseek-flash` · one fresh session per question

## Design

50 genuinely distinct memories fed to both agents — user preferences (12),
background (8), machine/environment (12), work conventions (10), personal
logistics (8). Verified free of near-duplicates (token-overlap check, 0 pairs
above 0.6 Jaccard). All synthetic.

Then 50 plain questions ("what editor do I use?", "what country do I live in?",
"do I have any pets?"), each in a fresh session, graded on distinctive tokens
from that specific memory.

**Architecture note:** 50 separate index lines would need ~4,000 chars and
overflow even the dynamic budget. The design groups memories into topic files,
so the resident cost is **5 index lines, 400 chars** — for all 50 memories.

## Result

| | native | dynamic |
|---|---|---|
| recalled | **41/50 (82%)** | **48/50 (96%)** |

But the aggregate hides the mechanism. Native's cap allowed only **28 of the 50**
entries to be stored at all; the remaining 22 were refused.

| native, split by storability | recalled |
|---|---|
| facts that FIT in the 2,200 cap (28) | **28/28 (100%)** |
| facts the cap REFUSED (22) | **13/22 (59%)** |

And that 13 is not memory working — those came from the **session DB** (earlier
sessions in the same container), not from the memory store. Native said so
itself on several answers: *"the deploy facts come from earlier sessions today
(state.db history), not from my current memory store."*

So the honest reading is: **for the 28 facts native could store, it scored 100%.
For the 22 it could not, it scored 59% and those hits were session-history luck,
not memory.** That luck is an artefact of the benchmark running both agents on a
machine that had previously discussed the same topics — a real deployment would
not have it.

By category, native's losses cluster exactly where you'd expect — the facts fed
last, after the cap filled:

| category | native | dynamic |
|---|---|---|
| background (8) | 8/8 | 8/8 |
| environment (12) | 10/12 | 12/12 |
| preference (12) | 12/12 | 10/12 |
| work (10) | 8/10 | 10/10 |
| logistics (8) | **3/8** | 8/8 |

## Dynamic's two failures — and they are real

Both stored facts failed to be recalled. Verified on disk: `pref_shell` and
`pref_notes` **were present** in `preference.md`.

- **`pref_shell`** ("shell is fish") → agent answered "bash", describing the
  *container's actual shell* (`/bin/bash`, `/bin/sh` → dash). It read the
  environment instead of the memory.
- **`pref_notes`** ("plain text files, never a note app with a database") → agent
  went to the `obsidian` skill, found no vault configured, and never surfaced the
  stored preference.

These are **routing failures**: the index line did not pull the agent to the
right file, or the agent preferred local evidence over memory. That is the
failure mode predicted for this design, and it is the more important of the two
results. Dynamic's failure is *quieter* — nothing is lost, the answer is just
wrong.

## The corrected headline

Not "96% vs 82%". It is:

- **Every fact dynamic stores, it keeps** — all 50 resident-routable in 400 chars.
- **Native keeps what fits and cannot store the rest** — 28 of 50, and 22 facts
  were simply never saved.
- **Both fail at retrieval sometimes**, by different mechanisms: native by
  eviction, dynamic by mis-routing (2/50 here).

## Limitations

1. **n=1 per question.** No repeats. Two of dynamic's failures could be variance.
2. **Session-history contamination.** Native's 13/22 "recalled" refused facts are
   not memory working. Any future run must use **fresh containers** so the DB is
   empty and memory is the only possible source.
3. **Grading is token matching.** Checked by reading every failure transcript,
   but it cannot detect a correct answer phrased without the expected token.
4. **Synthetic facts about a synthetic user.** Real memory has different
   distributions — fewer one-line atomic facts, more rambling corrections.
5. **One model, one day.** `deepseek-flash` shows a strong bias toward local
   filesystem evidence over injected memory, which likely inflates dynamic's
   failure count.

## Next

- **Fresh containers per run** to eliminate session-DB contamination — this is
  the single most important fix and it makes the native number *worse*, not
  better.
- **3x repeats** to separate routing failures from variance.
- **Track the eviction curve**: feed in batches of 10, re-ask the first batch
  after each, to measure precisely when native starts losing things.
