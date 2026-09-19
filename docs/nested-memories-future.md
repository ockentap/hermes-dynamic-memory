# Nested memories — future concept, not implemented

Recorded 2026-09-19 as a design direction. **No code exists for this.** Written
down so the idea and its concrete blockers are not lost.

## The idea

Memories that reference other memories: entry A routes to memory B, which routes
to memory C. A small resident index could then address a deep tree of detail,
giving high complexity at low resident cost — the same trade this project
already makes, applied recursively.

## Concrete blockers found in the current code

These are the specific things that would need to change, verified against the
current implementation.

**1. The validator forbids nested paths.**
`scripts/verify_index.py` lines 89-91 reject any target containing `/`:

    if "/" in target or target.startswith("~"):
        bad.append(("TARGET NOT BARE", line))

Targets must be bare `.md` filenames in a single directory. Nested directories
require relaxing this check in a way that still prevents escapes.

**2. Duplicate targets are rejected, so two entries cannot share a file.**
Same file, lines 92-94. A DAG where multiple memories point at one shared
sub-memory would trip this.

**3. The anti-orphan check assumes a flat namespace.**
Lines 121-124 require every file on disk to be referenced by exactly one index
line. A nested tree means intermediate nodes exist solely to be pointed at by
other nodes, which the current check would flag as orphans.

**4. The write-lock hook keys on a filename, not a path.**
`plugin/memory-shaper/plugin.py` enforces the format on writes to `MEMORY.md`.
Nested routing would need the lock and the format checks to follow the traversal
rather than guard a single flat file.

## Open design questions

- **Fan-out cost.** If each hop requires a file read, a 3-hop traversal is 3
  reads. Whether that is cheaper than one larger flat file at the same total
  detail is unmeasured — the flat index already reaches 12-18 chars of content
  per resident char, so the gain has to come from somewhere specific.
- **Termination.** Cycles (A -> B -> A) need a visited-set or a hop limit.
- **Failure mode.** With a flat index, a failed route means one wrong answer.
  With nesting, a broken intermediate node hides an entire subtree, and it is
  harder for the agent to notice it never arrived.
- **How much does routing accuracy degrade per hop?** The flat index already
  shows routing failures (~8% in the clean cohort run, e.g. `pref_shell`
  answering from the container's shell instead of memory). If each hop costs
  similar reliability, deep chains may compound the loss faster than they add
  capability. **This is the measurement to make before building anything.**

## The honest framing

Worth testing only if a deep tree beats a flat index of the same total detail at
the same resident cost. The complexity gain is plausible; the hop cost is
unmeasured, and the current 20-keyword index already achieves the coverage results
in the cohort benchmark. Instrument before implementing.

## Status

Future work. Not on the roadmap, not started, no estimated date.
