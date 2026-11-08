# Maybe list

Ideas considered for dynmem, with the decision attached. Nothing here is built
unless it says so. Newest first.

## Per-turn silent candidate block — approved direction, not built

**Idea (Lav, 2026-11-08)**: inject a hidden block with every user message — "which
memory files from the index should be updated judging by this session? answer
only relevant file names" — so the agent and its subagents carry a write plan
from the first turn.

**Decision**: yes to the block, no to a model call per message. The lexical IDF
scorer already returns the shortlist for free (same one that scored 100% fact
retention in the prefilter test), and a per-message model call would add a
request and latency to every turn.

**Shape when built**:
- computed from the latest user message (+ the previous turn) with
  `optimize.candidate_block`, no API call
- 2–4 files, declarative wording, never a question:

      [memory candidates] aklima-android-app.md, vaultwarden.md.
      Update one of these if the facts belong there; create new otherwise.

- cached in session state so `optimize.py` reuses it instead of recomputing
- advisory only: `memwrite` still validates the write, so a wrong candidate
  cannot become a wrong engram on its own
- measured cost as drafted: 29–36 tokens per turn, ≈3–4 effective once cached

**Open when built**: score floor (the weather-station message surfaced
`esp32-weather-clock.md`), and whether to add the 5 most recent neurons as a
constant block so a just-created topic stays visible for the next update.
