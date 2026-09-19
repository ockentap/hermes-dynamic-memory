---
name: dynamic-memory
description: Two-tier keyword-index memory for Hermes Agent — a ~400-token always-resident keyword index routes to verbose topic files read on demand. Enforced by the memory-shaper plugin.
version: 1.0.0
---

# Dynamic Memory (keyword-index edition)

Keep the always-resident part of memory tiny (a few hundred tokens) while letting total memory grow without bound. Verbose topic files live on disk; only a one-line keyword pointer per file is ever resident.

## Architecture — two tiers

| File | Format | Written with |
|---|---|---|
| `~/.hermes/memories/MEMORY.md` | `keyword,keyword,keyword → file.md` (one line per topic file) | the `memory` tool only |
| `~/.hermes/memories/<slug>.md` | verbose markdown | `write_file` (not locked) |

**`MEMORY.md` IS the index.** There is no separate `memory-index.md` — a second file with the same role creates ambiguity, and agents "fixing" memory to match phantom docs cause real drift. One file, one role.

The index is injected verbatim into the system prompt at session start as a frozen snapshot: mid-session writes hit disk immediately but do not touch the running prompt, which keeps the prefix cache valid. The block ends with routing instructions telling the model to treat the lines as a routing table.

## Retrieval: set-level keyword matching

When the conversation touches several keywords from one line — or an obviously related term not spelled out in the line — read that file in full before answering. Prefer the line whose keyword **set** matches best overall, not the first line sharing a single word:

- **Set-level, not per-keyword.** Score the whole comma-separated set per line. This resolves collisions like `java` (the JVM) versus `javascript` (the build toolchain): the toolchain line carries `npm`, `bundler`, and `node`, so "the java script for the build is broken" routes to the toolchain file even though both lines begin with the same letters.
- **Model-side fuzziness.** The model makes associative jumps over the literal index — "the fans won't stop spinning" routes to a line carrying `thermal` — so retrieval stays plain text with no embedding engine and no similarity threshold.

## Write protocol (memory tool only)

1. **Create the topic file first** — `write_file` → `~/.hermes/memories/<slug>.md`.
2. **Then add exactly one index line** via the `memory` tool:
   `keyword,keyword,keyword → file.md`
3. The plugin validates: bare `.md` target (no paths), 5–20 lowercase comma-separated keywords, no duplicate targets, one line per file. Malformed lines are refused with an actionable message (arrow errors are called out separately — the format uses Unicode `→`, U+2192).

## Qualifier prefixes (user-assigned only — never self-assign)

- `!!` critical — never edit this entry or its topic file without explicit user approval; propose the change, state the reason, stop and wait.
- `!` pinned — never prune; content may still be updated.
- untagged — normal; ordering and pruning may move or remove them.

## Ordering and budget

- Entries are ranked by how often their topic file is actually read (most-accessed highest); new entries go at the top of the untagged region.
- When the character cap is exceeded, prune from the bottom. Tagged entries are never reordered and never pruned.
- Keyword bounds: floor 5, ceiling 20, aim for 12+. Never pad with generic words — a vague or wrong keyword costs more than a missing one.
- When editing a topic file, update its keywords in the same pass. A line that no longer describes the file's content is a stale pointer, and a new concept added without matching keywords is unreachable.

## Governance — why the plugin exists

Agents drift, and self-editing memory is the most dangerous surface they touch. The plugin enforces the invariants that format validation alone cannot:

- **Structural replace guard.** `old_text` must match exactly one entry line, and a replacement may never reduce the entry count by more than one. This makes whole-file clobbering structurally impossible.
- **Format enforcement.** Arrow form, target shape, keyword bounds, and a comma-to-word ratio that rejects prose in index lines — each violation rejected with a targeted fix message rather than passing through.
- **Write-lock without audit lockout.** Read-only commands (`cat`, `grep`, `wc`, `diff`, `stat`) pass through so the agent can always inspect the index it maintains, while every write vector (redirect, `tee`, `sed -i`, command substitution, `write_file`, `patch`) is blocked when it references MEMORY.md.
- **Orphan and dead-target detection.** The validator flags topic files with no index line and index lines pointing at missing files, on every candidate write.

## Sizing reality check

A 60–70 line index (~500–600 keywords) costs roughly 350–500 tokens per turn at session start — and that is the entire always-resident overhead. For comparison, a single vector-store retrieval round-trip usually costs more tokens than an index line costs across a whole session. If the index outgrows this range, split by profile or by tier (pinned / active / archive) rather than introducing a database.
