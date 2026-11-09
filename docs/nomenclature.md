# Nomenclature

Three kinds of neuron, one edge. The vocabulary describes what a store actually is,
not a structure it might grow into: every part of dynmem is a neuron, and the role
decides which kind.

| Term | What it is |
|---|---|
| **neuron** | any node of dynmem — the index, a synapse or an engram. The umbrella word: used when the role does not matter, or for all three kinds at once |
| **index** | `MEMORY.md` — the root neuron and the only one with no parent; always resident, one line per child neuron |
| **synapse** | a neuron whose role is to pass the walk on: it holds **no memory text** — only its keyword line and its `when` edges |
| **engram** | a terminal neuron: the memory itself lives there |
| **link** | one `when … → child.md` edge; following it is a **hop** |

A synapse is a router, not a note: a table of route lines
(`keyword,…,keyword → child.md`), nothing else. Its own keywords live on the line
that points at it, in its parent's table. An engram carries content and no
keywords at all. The index is a neuron too — a routing table whose lines are its
edges, and the one neuron nothing points at; `MEMORY.md` is its fixed name. A flat
store is `index → engram`. Splitting a fat engram turns it into a **synapse** whose
children are engrams, or further synapses. Nothing is renamed on disk when a file
changes role: the edges decide.

## Tiers

| Tier | Station |
|---|---|
| **T1** | the index lines |
| **T2** | the child neurons the index points at |
| **T3** | their children |
| **T4** | third neuron |
| **T5** | the engram — the last station |

A tier is one more than the `--tree` depth, which counts the indexed file as depth 1. T1 is
the index line itself; the file it points at is T2. Keep the two vocabularies straight or the
uniqueness check reports nonsense.

## Keywords per station

- Every line at every tier carries **5–20 keywords**, the first five **locked** to the
  optimizer. See [`keyword-tiers.md`](keyword-tiers.md).
- Keywords are unique **within** a tier and may repeat **across** tiers: a synapse repeats
  words from the index line that points at it, by design.
- **Markers are index-only.** `!`, `!!`, `!!!` decide retention, and retention is a policy of
  the index (the root neuron); a synapse or engram line carries none.

## Retired draft

An earlier draft used nucleus / dendrite / axon / ganglion / terminal. It survives only in
older benchmark text, where it maps as: nucleus → index, dendrite → index line, axon → a
synapse's keyword line, ganglion → synapse, terminal → engram.
