# Demo: set-level keyword matching vs. single-keyword matching

Three conversations, run against the same index, to show where the two
approaches diverge.

## Setup

Relevant index lines:

```
java,springframework,jvm,garbagecollection,heap,profiling,jmx → java-performance.md
javascript,typescript,npm,bundler,webpack,vite,node,lint → js-toolchain.md
laptop,thinkpad,firmware,battery,thermal,fankey,bios → laptop-hardware.md
router,firmware,openwrt,modem,subnet,dns,dhcp → home-network.md
```

## Case 1 — "the java script for the build is broken"

Single-keyword matching is the failure mode here:

- The JVM line contains `java`
- The JS line contains `javascript`
- A per-keyword (or substring) scorer hits both and ranks them equally — the
  agent reads the wrong file, or both, and burns context doing it

Set-level matching instead weighs each line as a whole:

| line | keywords that fit the conversation | verdict |
|---|---|---|
| `java,...` | `java` (1, and only as a prefix of "javascript") | weak, incidental |
| `javascript,...` | `javascript` + `build`-adjacent tooling terms | strong, dense, specific |

The winner is `js-toolchain.md`. The signal is the *density and specificity of
the whole set*, not the presence of any single token. The model supplies the
judgment — it knows "the java script for the build" is about a build script,
not about the JVM, and that a frontend build is a `bundler` question.

## Case 2 — "heap keeps growing and GC pauses are getting long"

Same structure, opposite answer:

| line | keywords that fit the conversation | verdict |
|---|---|---|
| `java,...` | `heap` + `garbagecollection` (two from the same line, forming a real concept) | strong |
| `javascript,...` | none meaningful | no match |

The winner is `java-performance.md`. Note that the word "java" never appears in
the conversation at all — the line wins on `heap` and `garbagecollection`
alone, which a literal string lookup on the project name would have missed.

## Case 3 — associative matching over a literal index

User says: *"my laptop's fans won't stop spinning even at idle."*

No index line contains `fans`. The laptop line carries `laptop,thinkpad,
firmware,battery,thermal,fankey,bios`. The model — not an embedding engine —
makes the jump **fans → thermal**, scores that set as the match, and reads
`laptop-hardware.md` before answering.

This is the counterpart to Case 1: where set-level matching removes false
positives, associative matching recovers *true* positives that a literal lookup
would miss. Fuzziness comes from the model that is already in the loop, so
retrieval stays a plain-text file read with zero extra infrastructure — no
vector store, no similarity threshold, no embedding bill.

## What the routing instruction says

The index block in the system prompt ends with instructions along these lines:

> Treat these lines as a routing table. When the current conversation touches
> several keywords from one line — or an obviously related term not spelled out
> in the line — read that file in full before answering. Prefer the line whose
> keyword set matches best overall, not the first line sharing a single word.

Running the demo yourself: copy [`memories/`](memories/) into
`~/.hermes/memories/` (keeping a backup of your own), restart the agent, and
hold the three conversations above. Watch which file the agent reads.
