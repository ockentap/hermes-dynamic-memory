# Nomenclature

Three stations, one edge. The vocabulary describes what a store actually is, not a
structure it might grow into.

| Term | What it is |
|---|---|
| **index** | `MEMORY.md` — one line per neuron, always resident |
| **neuron** | any memory file (used only when the role does not matter) |
| **synapse** | a neuron with links: it exists to pass the walk on, and it holds **no memory text** — only its keyword line and the `when` edges |
| **engram** | a terminal neuron: the memory itself lives there |
| **link** | one `when … → child.md` edge; following it is a **hop** |

A neuron is a router, not a note: keyword line plus links, nothing else. If a
router still carries body text, that text belongs in an engram
(`<neuron>-overview.md` does it automatically). A flat store is `index → engram`. Splitting a fat engram turns it into a **synapse** whose
children are engrams, or further synapses. Nothing is renamed on disk when a file changes
role: the edges decide.

## Tiers

| Tier | Station |
|---|---|
| **T1** | the index lines |
| **T2** | the neurons the index points at |
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
  the index; a neuron line carries none.

## Retired draft

An earlier draft used nucleus / dendrite / axon / ganglion / terminal. It survives only in
older benchmark text, where it maps as: nucleus → index, dendrite → index line, axon → a
neuron's keyword line, ganglion → synapse, terminal → engram.
