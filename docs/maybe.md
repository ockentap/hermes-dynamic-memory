# Maybe list

Ideas considered for dynmem, with the decision attached. Nothing here is built
unless it says so. Newest first.

## Docker Hermes image for provider tests — deferred (Lav, 2026-11-08)

**Why**: a real agent-level comparison needs the actual Hermes loop, not API calls
in a script. An isolated image makes that repeatable and leaves the live profiles
alone.

**What we know**: the public repo ships no Dockerfile — its benchmarks reference
`hermes-native:0.21.3` and `hermes-dynmem:1.4.3`, which were never published.
A local stand-in was built instead: two profiles (`dyn18` with dynmem 1.8.0 from
`698ff20`, `dyn11` with the 1.11 plugins), same 196-file corpus, `hermes -z
--usage-file`.

**The blocker that surfaced**: `pre_llm_call` does not fire in `-z` or piped
`chat` mode (instrumented hook log stayed empty), so memlook's auto-injection
never ran and both runs fell back to index-only behaviour and filesystem grep.
Lav reports another Hermes agent already fixed this — confirm the fix before
building the image.

**When built**:
- base image with Hermes 0.23.x, no profile data
- seed a fixture store per provider (flat 1.8.0 / tree 1.11 / built-in cap)
- run the 20-question realistic corpus through the gateway path, not `-z`
- measure requests, total tokens (cache-aware) and correct answers per provider
- keep the image out of the live profiles; key via env at run time

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
