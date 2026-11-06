# Blocks — what dynmem is made of, and who is allowed to write what

A map for maintenance, not a tutorial. It answers one question: **if I change this,
what else can break?** Blocks are drawn by write territory, because that is where
coupling actually lives — two components that only read the same file are independent;
two that write it are not.

State as of 2026-11-04.

---

## 1. Store & format

| | |
|---|---|
| Files | `~/.hermes/memories/MEMORY.md`, `<topic>.md`, `USER.md`, `archived memories/` |
| Owns | the data model: one line per file, 5–20 keywords, Unicode `→`, header ends at the template line, topic files verbose and indexed |
| Writer | none of its own — it is data |
| Validators | `scripts/verify_index.py`, `memory-integrity-checker/scripts/check_memory.py` |
| Readers | everything else |

The invariant both directions: every line resolves to a file, every topic file has a line
(or is named in the header). Orphans in either direction fail silently.

## 2. Write guard

| | |
|---|---|
| Files | `plugin/dynmem/plugin.py` (55 KB, 29 functions, 1.5.1) |
| Hooks | `pre_tool_call` + `tool_execution` middleware |
| Owns | refusing prose, overlong content, ASCII arrows, path targets, keyword counts out of band, header/template edits; blocking shell write vectors at the index |
| Writer | never — it only vetoes |
| Entry points | `handle_pre_tool_call`, `handle_tool_execution_middleware` |

Four concerns live in one file: **format validation**, **write-vector blocking**,
**header/template protection**, and plugin registration. A rule added to one dispatch
path can be missing from another — the ASCII-arrow rejection existed on the single-op
path and the patch path, and was absent from `operations[]`, which is the path current
Hermes uses. That gap was structural, not careless.

## 3. Keyword lifecycle

| | |
|---|---|
| Files | core `agent/memory_optimization.py`, `memories/.keyword-provenance.json`, `plugin/dynmem/` (band checks) |
| Owns | the positional locked block (first 5), the model band 5–15, the hard 20 cap, provenance of machine-added words, proposals and the swap margin |
| Writer | `memory` tool only — the optimizer proposes `old_text`/`new_text`, a caller applies |
| Job | **none running.** `Daily Memory Maintenance` and `memory-integrity-nightly` are both `enabled: false` |

Nothing maintains keywords today. The lock still holds — it is positional, so it holds
on a store that never ran the optimizer — but no proposals are generated.

## 4. Ordering & eviction

| | |
|---|---|
| Files | `scripts/dynmem-watchdog.py` (29 KB) |
| Job | `dynmem-watchdog`, cron `17 5 * * *`, `no_agent`, silent unless it archives |
| Owns | access tally (`.access-tally.json`), 30-day window ranking, permutation reorder, archive past ~95% of the cap |
| Writer | **the only block that moves lines wholesale** — and only as a permutation, with multiset assertions before and after |

## 5. Prompt-side retrieval

| | |
|---|---|
| Files | the header block inside `MEMORY.md` (search order, MCP sentence, marker legend, one purpose line per dynmem document) |
| Owns | telling the model that the index is a pointer table and how to fall through when it misses |
| Writer | hand-curated, no code |
| Depends on | nothing. It travels inside the injected file |

This is load-bearing prose: Hermes attaches no instruction of its own, so deleting the
header removes the fallback path with it.

## 6. Evidence

| | |
|---|---|
| Files | `plugin/dynmem/memcheck.py` (26 KB), `memcheck_hooks.py` (7 KB), `scripts/memcheck_report.py`, `scripts/gate_oracle.py`, `test_retrieval.py`, `test_hook_cases.py`, `benchmarks/` |
| Hooks | `pre_llm_call`, `transform_llm_output` |
| Owns | observation: which files were opened, which nearly were, whether a routing was contradicted, and the benchmarks that measure any of it |
| Writer | never against the store; it writes `~/.hermes/state/memcheck/*` |
| Installed | **no** — repo is 1.6.0, `~/.hermes/plugins/dynmem` is 1.5.1 |

It duplicates `parse_index` on purpose: the observer must not inherit the guard's bugs.

## 7. Wiring

| | |
|---|---|
| Files | `~/.hermes/cron/jobs.json`, `config.yaml` (`memory.memory_char_limit`, `memory.nudge_interval`), `scripts/patches/0001-flat-memory-separator.patch`, plugin install/sync |
| Owns | schedules, budgets, the core patch that keeps the store flat, and the copy of the plugin the gateway actually imports |
| Failure mode | silent. A disabled job, a stale install, or a lost patch looks identical to "nothing to report" |

Live jobs touching memory: `dynmem-watchdog` (05:17), `mempalace-remine` (03:17),
`memory-patch-guard` (09:00), `memory-consolidate-monthly` (1st, 04:00). Disabled:
`Daily Memory Maintenance`, `memory-integrity-nightly`.

---

## Write territory for `MEMORY.md`

Three blocks write it, in three different ways. Nothing else may.

| Block | Kind of write | Guard it must go through |
|---|---|---|
| 2 Write guard | none (vetoes only) | — |
| 3 Keyword lifecycle | span replacement via `memory(action="patch")` | 2, on every dispatch path |
| 4 Ordering | whole-file permutation, markers pinned | its own multiset assertions + 2's format rules |
| 7 Wiring | patch restore, install/sync | 2 |

Consequence: a new writer that bypasses block 2 will eventually produce a line that
`verify_index.py` and the watchdog both accept but the model cannot route.

## Dependency arrows

```
1 Store  ←── written by ── 3 (spans), 4 (permutation)
   ↑ read by
2 Guard ── reads file to validate ──┐
3 Lifecycle ── proposes via ────────┤
4 Ordering ── reads tally ──────────┤
6 Evidence ── reads index + bodies ─┘   (own parser, deliberately)
5 Header  ── injected with the file, depends on nothing
7 Wiring  ── starts 3, 4, 6 and installs 2
```

Changing 1 breaks everything. Changing 5 is free. Changing 2 without running 6's
tests is how format rules drift. Changing 4 without 3 is safe; changing 3 without 4
can reorder newly added lines on the next run.

## Known structural weaknesses

1. **Block 3 has no owner.** Keywords are maintained by hand or not at all. Re-enable a
   job scoped to the files a session touched, not a store-wide sweep (~16 s, 85
   proposals, almost all already known).
2. **Block 2 is four blocks in one file.** Split into `format_guard`, `write_vector`,
   `header_guard`, with one entry point that calls all three and one validator object
   shared by every dispatch path. The ASCII gap is the argument: a rule enforced by a
   predicate must be run by every path, and a path added later is the one that skips it.
3. **Block 6 is not installed**, so every number it could produce is currently zero.
4. **Block 7 is invisible.** No report says "job disabled", "plugin stale", "patch
   missing". Those three states are indistinguishable from a healthy system.

## Checklist for changing a block

- Touching 1 or 4 → run `verify_index.py` before and after; assert the multiset.
- Touching 2 → run the plugin suite **and** the three existing dispatch paths
  (`operations[]`, legacy single-op, patch) with one case each; a green suite on
  `operations[]` says nothing about the other two.
- Touching 3 → check the locked block is still the first five by position, and that
  `cap_keywords()` is the last thing a line passes through.
- Touching 6 → re-run its tests with `--import-mode=importlib --noconftest`; the
  directory name is not a valid identifier.
- Touching 7 → prove the running build, not the repo: `gateway_state.json` → `argv[0]`,
  then the plugin's own startup line.
