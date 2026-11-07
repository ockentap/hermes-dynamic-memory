# Keyword tiers — 5–20 keywords at every tier, five of them locked

**Rule.** Every neuron carries its own keyword line, at every tier, with the same band as
the index: **5–20 keywords, the first five locked to the optimizer**. Keywords are
**unique within a tier** and **may repeat across tiers**, so a synapse naturally re-uses
words from the index line that points at it. See [`nomenclature.md`](nomenclature.md) for
the terms.

## Format

```markdown
keywords: cron,daemon,unit,schedule,retry,home/media/jobs.py,systemd,failure
# Cron jobs — what runs, what failed

...
```

- The line is the **first non-blank line of the file** — not after the heading. A reader
  that stops at the title must not miss it.
- Lowercase key `keywords:`; comma-separated; no spaces inside a keyword; ≤ 48 chars each.
- 5 minimum (the locked block), 20 maximum.
- **No marker.** `!`, `!!`, `!!!` are index-only; a neuron line has no retention policy.
- The index line format is unchanged (`keywords → file.md`); the per-file line is the same
  list without a target.

## Tiers

| Tier | Keywords live in | Picked by |
|---|---|---|
| T1 | `MEMORY.md` index lines | the agent, from the resident index |
| T2 | first line of each indexed neuron | the agent after opening the synapse, or `evalmem.py` |
| T3 | first line of each linked child | the evaluator, one hop down |
| T4, T5 | same, one line per neuron | same |

The ceiling is **T5**: `index -> neuron -> neuron -> neuron -> engram`. A path may
pass through at most three neurons, and whatever sits at T5 must be an engram —
a T5 neuron with children would need a T6 hop and fails (`TIER 5 MUST BE AN
ENGRAM`).

T1 is the index line; the file it points at is T2. That is **one more than `--tree` depth**,
which counts the indexed file as depth 1 — keep the two straight.

## The locked block

The **first five** keywords on any line — index or neuron — belong to the optimizer. They are
positional, not marked: no sidecar, no bootstrap on a store that never ran the optimizer.

- The optimizer may fill, swap or refine those five.
- The model pass may only add or remove keywords **after** the fifth. It must never reorder
  the line and never remove a locked keyword.
- A line at 20 keywords accepts nothing new until a human removes one.

## Uniqueness

```
T1  cron → automation-workflows.md        ← one owner at T1
T1  cron → newsdata-api.md                ← collision: same tier, same keyword
T2  keywords: cron,daemon,unit,...        ← legal: T1 vocabulary reused at T2
```

- **Within a tier:** one keyword, one neuron. Two T1 lines sharing `cron` means the first hop
  cannot discriminate; two T2 synapses sharing `frame` means the second hop cannot either.
- **Across tiers:** repeats are expected. Both describe the same memory.

Measured cost on a real 134-line store before cleanup: 267 keywords appeared on two or more
index lines, 98 of them inside the locked block (`cron` on 13 lines, `pi` and `tailscale` on
10 each). Every one adds a candidate the first hop cannot separate.

## Enforcement

```bash
python3 scripts/verify_index.py ~/.hermes/memories/MEMORY.md --tree --keywords
# keywords: 3 tier(s) [T1 2, T2 2, T3 2], 4 headers, 0 collisions
```

- `--keywords` is opt-in: a store written before the rule has no headers and must not fail CI.
- Checks: missing or misplaced header, marker on a neuron, 5–20 band, duplicate in line,
  spaces/length, and per-tier collisions.
- `scripts/split_memory.py` accepts `synapse_keywords` and per-leaf `keywords`, validates them,
  writes them as each file's first line, and runs the validator with `--keywords` when the
  tree is complete.
- **Not enforced at write time.** The dynmem plugin guards `MEMORY.md`; neuron files are
  written with ordinary tools. A bad header is caught by the validator, not the hook — adding
  that would mean intercepting every edit to every memory file.
- The optimizer is a separate component in the Hermes tree
  (`agent/memory_optimization.py`); it owns the locked block and the neuron-term proposals.

## Migrating an existing store

1. **Dedupe T1 first.** `--keywords` reports the collisions; fix them before adding headers,
   or T2 inherits an ambiguous vocabulary.
2. **Add headers top-down.** Every indexed neuron gets a T2 line; validate after each batch.
   Pick the free words from the file's own identifiers, never invent them.
3. **Only then split.** When a file is fat enough to become a synapse, it keeps its T2 line
   and each child gets a T3 line.

A retrofit writes every memory file: back up first and gate on the validator.

## Cost

A keyword line is ~15–25 tokens per file read. At T2 that is noise against the file it
replaces; at T4–T5 it compounds on every hop, which is the same reason deep trees stop paying.
