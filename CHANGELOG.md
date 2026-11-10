# Changelog

## 1.12.1 — 2026-11-10

- **`parse_index` reads the live keyword format again.** It split keywords on
  commas, which parsed **0 of 123 lines** on a 1.11 store (keywords are
  space-delimited), so every `opened`/`wrong`/`right` claim was rejected as
  `unknown_file` and every `hook` as untraceable. Commas are still accepted on
  read so pre-1.11 stores keep validating. Coverage on the two live stores went
  0% → 99%; a regression test pins the space form and the mixed form.
- **The plugin's own tests are in the default suite.** `pytest.ini` listed only
  `tests/`, so `test_memcheck.py`, `test_billing.py` and `test_operations.py`
  never ran — which is how the comma regression survived. 55 → 105 tests.
- Scrub "research samples" from the memcheck comment: the samples exist to score
  keyword candidates for the optimizer, not to collect data for us.

## 1.12.0 — 2026-11-09

Review fixes for the catalog PR (`NousResearch/hermes-agent#149712`, review by
@teknium1 on 2026-11-08):

- **memcheck is opt-in.** Default OFF; enable it with
  `plugins.entries.dynmem.settings.memcheck.enabled: true` (own config, not an
  env var). `MEMCHECK_DISABLED` stays as a one-process kill switch.
- **`hold_stream=True`** when the transform hook is registered, so the `<mc …>`
  tag cannot stream to the user ahead of the rewrite; falls back to the plain
  registration on Hermes builds without the kwarg.
- **Bounded samples.** `samples.jsonl` rotates at 5 MiB (`samples.jsonl.1` keeps
  one previous window) and the docs say exactly what a record stores, including
  the first 400 characters of the user message.
- Plugin modules import package-relatively (`from . import memcheck_hooks`) with
  a path-based fallback, instead of putting the plugin dir on `sys.path`.
- `scripts/test_hook_cases.py` no longer fails on its own fixtures: the index
  path follows `$HERMES_HOME` and the fixture lines use the space-separated
  keyword format (commas have been rejected since 1.11.0). 0 failures.
- **The one-time shape question actually ships.** `_billing_hook` had been wired
  since 1.11 without its module, so it failed open and asked nothing.
  `billing.py` now asks on the first human turn after install: *fewer requests*
  (flat index, one read per recall, more resident tokens) or *fewer tokens*
  (tiered index, 2-3 reads, far fewer tokens). The answer goes in
  `plugins.entries.dynmem.settings.profile`, the question is asked once, and the
  chosen shape is restated once per session. 6 new tests.

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
