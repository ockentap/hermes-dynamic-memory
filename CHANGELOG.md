# Changelog

## 1.11.0 — 2026-11-08

- Routers: every neuron is a table of route lines, `keyword keyword → child.md`;
  engrams carry no keywords and no related-links block.
- Keywords are space-delimited (commas removed), Unicode arrow only, 5–20 per
  line, unique inside one table.
- Write path: `scripts/memwrite.py` applies a plan to a shadow store, normalises
  every routing table, validates, backs up and only then writes. No index echo.
- Optimiser: `scripts/optimize.py` + the `memoptimizer` plugin — 15-minute idle
  hook (or a manual trigger file) that summarises new messages into engrams.
  Per-message watermark, IDF candidate prefilter instead of the full index.
- Write enforcement: the dynmem hook validates `write_file`/`patch` into the
  store — routers must be route lines only, targets must exist, keywords unique.
- Engram rules: one subject, 2–6 KB, 7 KB ceiling, split by aspect
  (`docs/engrams.md`); `verify_index --engrams` audits sizes.
- Tools: `split_engram.py`, `split_ranges.py`, `group_children.py`,
  `clean_routes.py`, `memwrite.py`, `optimize.py`, `bench_facts.py`.

## 1.10.0

- Neuron write enforcement and the lookup walk (previous release).
