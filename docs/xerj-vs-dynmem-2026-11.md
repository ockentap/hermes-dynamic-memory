# Dynmem vs XERJ — top-1 routing on a real store

Run: 2026-11-27 · XERJ `v1.0.0-rc.105` · router model `deepseek-v4.1-flash` · n=1 per prompt

**Headline: dynmem routed 40 of 40 prompts to the right topic file. XERJ, a
purpose-built AI search engine, reached 37/40 in its default lexical mode, 33/40 with hybrid
fusion and 30/40 with its neural embedder. The index wins on precision; XERJ wins on footprint,
latency and having something to search at all.**

This is a routing test, not an answer-quality test: the question is only whether the right
topic file is surfaced first. It is run against a private personal store, so the prompts, file
names and topics are not published — the aggregate results and per-prompt outcomes are.

## Setup

- **Store:** 149 index entries + 108 linked child files = **252 files**, 640 KB of Markdown,
  **488 chunks** at XERJ's own chunking.
- **Prompts:** **40** — 20 written in a keyword style an agent would type
  (model, protocol, symptom, component) and 20 as natural-language paraphrases that avoid the
  index's own vocabulary. Examples are withheld; the published outcomes are per prompt.
- **Ground truth:** the topic file that contains the answer. A hit on a child file counts for
  its parent hub; no other credit is given.
- **dynmem:** the keyword index only (no file contents) is given to the router model, which
  picks the file — the mechanism the system actually uses in a session. A mechanical keyword
  matcher and a keyword+grep fallback are reported separately as lower bounds.
- **XERJ:** fresh data dir on the same box, `--embed-mode lexical` (the default). Neural mode is
  `all-MiniLM-L6-v2`, indexed on CPU; hybrid is RRF over BM25 and MiniLM vectors.
- One run per system; no prompt was tuned after seeing a result.

## Results

| system | top-1 | top-3 | keyword prompts | paraphrase prompts | MRR |
|---|---|---|---|---|---|
| **dynmem — index routing (LLM)** | **40/40** | **40/40** | **20/20** | **20/20** | **1.000** |
| dynmem — mechanical keyword matcher | 31/40 | 35/40 | 19/20 | 12/20 | 0.812 |
| dynmem — keyword + grep fallback | 36/40 | 36/40 | 20/20 | 16/20 | 0.900 |
| XERJ lexical — `xerj search` CLI | 37/40 | 39/40 | 19/20 | 18/20 | 0.950 |
| XERJ lexical — ES `multi_match` | 37/40 | 37/40 | 20/20 | 17/20 | 0.925 |
| XERJ hybrid RRF | 33/40 | 35/40 | 17/20 | 16/20 | 0.846 |
| XERJ semantic (MiniLM) | 30/40 | 30/40 | 15/20 | 15/20 | 0.766 |

## What the numbers say

- **Dynmem is not beaten by better search.** XERJ's lexical mode is close on keyword
  prompts (19/20) and better than a naive keyword matcher on paraphrases (18/20 vs 12/20) — but
  it never closes the last three prompts, because a general ranker has to learn what this store
  already states: which file owns which subject.
- **XERJ's misses are collisions, not blanks.** All three are sibling topics that share
  vocabulary, plus one hub whose content lives in a linked child file: the hub is a two-line
  pointer while an unrelated document mentions the query terms. The right file was second twice
  and sixth once; top-3 recall is 39/40.
- **Embeddings make it worse here.** Whole-file chunks are 2–4 KB; MiniLM truncates at 256
  tokens, so the decisive paragraph can fall outside the vector. Semantic scored 30/40 and hybrid
  33/40 — seven prompts below BM25. Indexing the neural mode took 177 s for 488 chunks on CPU.
- **XERJ's real advantages are operational.** 3.9 ms per query server-side (50–70 ms through the
  CLI, which pays process start), a 2.1 MB lexical index, a 147 MB static binary, no resident
  tokens in the prompt, and an Elasticsearch-compatible API plus a 25-tool MCP server. dynmem
  pays ~4.5k resident tokens every turn and needs no process at all.

## Limits

- 40 prompts, one run, one store, one router model. Differences under ~10% are noise; 40/40 vs
  37/40 is not.
- The prompts were written by the same agent family that wrote the index, from the files' own
  vocabulary. That favours dynmem; a neutral sample would narrow the gap.
- Hub-level ground truth hides chunk-level retrieval quality: XERJ returns passages, dynmem
  returns a file the agent still has to read.
- The corpus in this run is the same set the index can reach. A production XERJ install can also
  index files dynmem never routes to; that is a coverage advantage this test does not
  measure.
- XERJ is a fast-moving release candidate; `rc.105` is the version tested.

## Reproduce

Aggregate results, per-prompt outcomes (anonymised, no text) and the chart source:

- [`docs/xerj-vs-dynmem-2026-11.json`](xerj-vs-dynmem-2026-11.json)
- [`scripts/make_chart_xerj.py`](../scripts/make_chart_xerj.py)
- [`docs/charts/xerj-routing-2026-11.svg`](charts/xerj-routing-2026-11.svg)

The XERJ build used here is the musl static tarball: the glibc build requires `GLIBC_2.43` and
does not start on Debian 13 (2.41). XERJ's own banner asks agents to submit a field report; that
was disabled with `XERJ_DISABLE_FEEDBACK=true` for the run.
