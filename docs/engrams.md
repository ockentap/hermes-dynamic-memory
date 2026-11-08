# Engrams

An engram is a terminal memory: the file a route line finally points at. Neurons
route; engrams explain. Everything below is about making an engram worth the
tokens it costs to read.

## The rules

1. **One subject per engram.** A subject is one thing you would ask about on its
   own: "the aKlima build", "the Pi-side watchdog", "the R5 preheat curve". If a
   file answers two unrelated questions, it is two engrams.

2. **Compact, with concentrated explanatory power.** Target **2–6 KB**, hard
   ceiling **7 KB**. The first paragraph states the conclusion or the state of
   play; the rest is the evidence that makes it true — commands, paths, values,
   ports, dates. Never a chronological log: a reader should get the answer
   without replaying the history.

3. **Split by aspect, not by size.** A subject that has distinct aspects —
   separate mechanisms, environments, versions, periods, or failure modes —
   becomes several sibling engrams, one per aspect:
   `aklima-android-app-what-it-is.md`, `aklima-android-app-pi-side-watchdog.md`,
   `aklima-android-app-r5-preheat-tail.md`. Each is linked by its **own route
   line in the neuron**, with keywords unique inside that table. The neuron is
   where the aspects meet; the engrams never link to each other.

4. **Small topics stay whole.** A single fact or a 300–1500 character note
   ("the arrow must be Unicode", "the gateway restart is service + webhook") is
   already one engram. Do not split for length alone, and do not pad a small
   topic to look substantial.

5. **No duplication.** A fact lives in exactly one engram. If two aspects need
   it, one owns it and the other is routed to it via the neuron — not copied.

6. **Shape of the file.** First line `# <title>`, second line
   `Part of: <neuron>.md.`, then the content. No `keywords:` header (the route
   line carries the identity), no `## Related memories` block (the neuron is the
   relationship), no arrow lines (those would make it look like a router).

7. **Naming.** `<neuron>-<aspect>.md`, lowercase, hyphens, aspect last:
   `vaultwarden-pi-account-recovery.md`, not `vaultwarden-2.md`.

## When to split an existing engram

Split when any of these is true:

- it is larger than **7 KB**;
- it has more than **five H2 sections** that are not one argument;
- it answers questions that belong to different neurons;
- you catch yourself adding a paragraph that starts "separately, …".

When you split, the old file's route line is replaced by one line per new
sibling, each with 5–20 keywords, all unique inside that neuron's table.

## Checking

```
python3 scripts/verify_index.py MEMORY.md --memdir <store> --engrams
```

reports the count, the median size, and every engram over the ceiling with its
size. `--tree --keywords` still validates the routing shape.
