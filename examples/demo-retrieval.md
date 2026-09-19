# Demo: set-level keyword matching vs. single-keyword matching

Two conversations, run against the same index, to show where the two approaches diverge.

## Setup

Relevant index lines:

```
camera,photography,dslr,lens,aperture,exposure,tripod,raw,editing → camera-gear.md
golf,clubs,swing,handicap,course,putting,driver,iron → golf-notes.md
car,maintenance,transmission,oil,tires,garage,service,brakes → car-log.md
```

## Case 1 — "the golf car battery is dead"

Single-keyword matching is the failure mode here:

- The golf line contains `golf`
- The car line contains `car`
- A per-keyword score hits both and ranks them equally — the agent reads the
  wrong file, or both, and burns context doing it

Set-level matching instead weighs each line as a whole:

| line | keywords that fit the conversation | verdict |
|---|---|---|
| `golf,...` | `golf` (1 — and only as part of "golf car") | weak, incidental |
| `car,...` | `car` + the vehicle/service set this discussion implies | strong, dense, specific |

The winner is `car-log.md`. The signal is the *density and specificity of the
whole set*, not the presence of any single token. The model supplies the
judgment — it knows a "golf car" is a vehicle and that a battery belongs to one.

## Case 2 — "which clubs should I replace"

Same structure, opposite answer:

| line | keywords that fit the conversation | verdict |
|---|---|---|
| `golf,...` | `golf` + `clubs` (two from the same line, forming a real concept) | strong |
| `car,...` | none meaningful | no match |

The winner is `golf-notes.md`. Note that "clubs" alone would be ambiguous;
paired with "replace" it is a sport question, and with "car" it would be a
vehicle question. The set, not the word, carries the meaning.

## Case 3 — associative matching over a literal index

User says: *"I'm thinking of upgrading my DSLR."*

No index line contains the string `dslr`. The camera line carries
`camera,photography,lens,aperture,exposure,tripod`. The model — not an
embedding engine — makes the jump **DSLR → camera**, scores that set as the
match, and reads `camera-gear.md` before answering.

This is the counterpart to Case 1: where set-level matching removes false
positives, associative matching recovers *true* positives that a literal
lookup would miss. Fuzziness comes from the model that is already in the
loop, so retrieval stays a plain-text file read with zero extra
infrastructure — no vector store, no similarity threshold, no embedding bill.

## What the routing instruction says

The index block in the system prompt ends with instructions along these lines:

> Treat these lines as a routing table. When the current conversation touches
> several keywords from one line — or an obviously related term not spelled out
> in the line — read that file in full before answering. Prefer the line whose
> keyword set matches best overall, not the first line sharing a single word.

Running the demo yourself: copy [`memories/`](memories/) into
`~/.hermes/memories/` (keeping a backup of your own), restart the agent, and
hold the three conversations above. Watch which file the agent reads.
