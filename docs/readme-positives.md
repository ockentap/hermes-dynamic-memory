# Dynmem — verified strengths (source material for the README)

Every claim below is from a measured run on 2026-11-05, Hermes v0.22.5, `deepseek-v4.1-flash`,
on a 142-topic / ~200 KB personal memory store (the real one, not a demo). Numbers are reproducible
with `~/hackathon-demo/bench/` (route_bench.py, run_real2.py, real_results*.json).

## 1. It routes to the right memory

- Deterministic index routing: **10/10 prompts → correct topic file first** (`route_bench.py`,
  ten real first-user-messages from actual sessions).
- In an agent run with a 2-tool budget: **7/10 prompts opened the correct file**.
- Best competitor on the same corpus (entropicmem, 1,820 bullet facts): **4–5/10 top-1**, 3/10
  grounded answers.

One-line claim: *the index picks the right file; FTS-based stores pick it about half the time.*

## 2. It costs almost nothing to write

- Ingest of 24 topics: **≈0 tokens** beyond the writing turn itself. Topic file + one index line.
- Competitors paid for distillation: entropicmem 59 s / 89k tokens, chronicle 128 s / 148k,
  openltm 143 s / 325k, intelligent_memory 176 s / 175k.
- No embeddings, no background extraction job, no LLM pass over every turn.

One-line claim: *memory is written at the speed of a file write.*

## 3. It keeps the prompt small

- Idle cost per turn: **6.8–6.9k tokens** with dynmem vs **13.9k** for stock Hermes memory.
- Level with the best memory providers (6.4k–8.5k), without a database or an embedding model.

One-line claim: *half the per-turn cost of the built-in memory, with none of the infrastructure.*

## 4. It is complete, not approximate

- Retrieval returns the **whole topic file** — the answer cannot be ranked seventh and dropped.
- Top-k snippet stores can miss; a file read cannot.

One-line claim: *no top-k truncation, no "the fact was in the store but not in the prompt".*

## 5. It has no infrastructure

- Markdown files in one directory. No SQLite, no Qdrant, no server, no API key, no model download.
- Works offline; greppable, diffable, backed up like any text.
- Survives a host rebuild by copying one folder.

## 6. It is guarded

- `dynmem` enforces the index format (Unicode arrow, bare filename, 5–20 keywords), rejects
  prose, refuses writes to the header, and blocks shell writes to `MEMORY.md`.
- `verify_index.py`: duplicate targets, orphan files, keyword bounds, and — since 1.7.0 —
  `## Related memories` edges (max 5, condition required, missing target, self link, cycles).
- No competitor in the test ships an equivalent validator.

## 7. It improves with a better model, and that is measurable

- v1.7.0 (absolute path line + read rules + Related edges) on the same prompts:
  `energy prices` 3 calls / 42.4k → **2 calls / 25.8k, 97.5 s → 26.8 s**.
- On a weak free model the advantage narrows (8 calls, 66.6k) — say so in the README; it is honest
  and it frames dynmem as a system for capable models.

## Where competitors still lead (put this in the README too)

- **Recall cost per hit:** entropicmem injects 100–250-token snippets; a dynmem file read is ~1.3k.
- **Model independence:** prefetch-based providers answer in 1–3 calls even on a weak model.
- **Semantic matching:** FTS/vector recall catches paraphrase; the keyword index needs a keyword.
- **Latency:** their routing is 5–10 ms; ours is a model decision plus one tool call.

## Claims we must NOT make

- "Best memory system" — the ranking flips with model strength and corpus shape.
- "Cheapest per answer" — true only when the model routes in one shot.
- "Works with any model" — measured false on `nemotron-3.5-lightning:free` (8 calls vs 2–3).
