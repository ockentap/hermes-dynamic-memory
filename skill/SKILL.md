---
name: dynamic-memory
description: "Two-tier keyword-index memory for Hermes Agent. MEMORY.md is a flat keyword index (keyword,keyword → file.md) injected into the system prompt each session; verbose detail lives in topic files read on demand. Covers the write protocol, retrieval routing, the routing-instruction requirement, and diagnosis of the failure modes that silently break recall."
version: 2.0.0
author: ockentap
license: Apache-2.0
tags: [memory, context, dynamic-memory, keyword-index, routing, MEMORY.md]
triggered_by: [memory, dynamic memory, memory index, keywords, recall, write memory, MEMORY.md, memory not working, orphan, routing]
related_skills: [memory-integrity-checker]
---

# Dynamic Memory (keyword-index edition)

Keep the always-resident part of memory tiny (a few hundred tokens) while letting total memory grow without bound. Verbose topic files live on disk; only a one-line keyword pointer per file is ever resident.

## What this is

`MEMORY.md` is a **lookup table, not a notebook**. It is injected into the system prompt at every session start. Each line maps a set of keywords to a topic file in the same directory. When a query matches a keyword, the agent reads the linked file for the detail. That is the whole system.

## Architecture — two tiers

| File | Format | Written with |
|---|---|---|
| `~/.hermes/memories/MEMORY.md` | `keyword,keyword,keyword → file.md` (one line per topic file) | the `memory` tool only |
| `~/.hermes/memories/<slug>.md` | verbose markdown | `write_file` (not locked) |
| `~/.hermes/memories/USER.md` | identity facts only, prose, separate char cap | the `memory` tool, `target='user'` |

**`MEMORY.md` IS the index.** There is no separate `memory-index.md` — a second file with the same role creates ambiguity, and agents "fixing" memory to match phantom docs cause real drift. One file, one role.

The index is injected verbatim into the system prompt at session start as a frozen snapshot: mid-session writes hit disk immediately but do not touch the running prompt, which keeps the prefix cache valid. New entries therefore become visible to the *next* session, not the current one.

**The invariant (both directions must hold):**

- Every index line must point to a file that exists in `~/.hermes/memories/`.
- Every topic file in `~/.hermes/memories/` must be referenced by an index line.

Orphans in either direction silently break recall: a topic file with no line is unreachable, and a line with no file is a dead pointer. Neither surfaces an error at runtime — only a validator catches them.

## Retrieval: set-level keyword matching

When the conversation touches several keywords from one line — or an obviously related term not spelled out in the line — read that file in full before answering. Prefer the line whose keyword **set** matches best overall, not the first line sharing a single word:

- **Set-level, not per-keyword.** Score the whole comma-separated set per line. This resolves collisions like `java` (the JVM) versus `javascript` (the build toolchain): the toolchain line carries `npm`, `bundler`, and `node`, so "the java script for the build is broken" routes to the toolchain file even though both lines begin with the same letters.
- **Model-side fuzziness.** The model makes associative jumps over the literal index — "the fans won't stop spinning" routes to a line carrying `thermal` — so retrieval stays plain text with no embedding engine and no similarity threshold.

### Routing instructions are NOT injected for you

Stock Hermes renders `MEMORY.md` into the system prompt under a `MEMORY (your personal notes)` header and **stops there**. It does not attach any instruction telling the model that the lines are pointers, that they should be treated as a routing table, or that matching files should be read before answering.

The index arrives as a bare list. Without an explicit routing instruction somewhere the model reliably sees, a capable model will often still find the right file — but by *searching the filesystem* (`search_files`) rather than by routing from the index. That produces correct answers at one topic file and fails at a hundred.

**Supply the routing rule from one of two places:**

1. **This skill (recommended).** The rule below is part of this skill's retrieval section; loading the skill carries it into context.
2. **System prompt / personality.** Put it in your personality file or `config.yaml` so it is present in every session regardless of skill loading:

   > Your memory index is a routing table, not a summary. When the conversation touches several keywords from one line — or an obviously related term the line doesn't spell out — read that file in full before answering. Prefer the line whose keyword set matches best overall, not the first line sharing a single word.

### Never stop at "no memory of that"

`MEMORY.md` is a curated subset, not the whole knowledge base. When no keyword matches, or the matched file doesn't answer the question, do not stop and report that you have no memory of it. Search further, in this order:

1. Scan the index (already in context) → read the linked topic file.
2. `mempalace search "<query>" --results 5` — mined session history, if available.
3. `session_search(query="...")` — conversation transcripts.
4. Read the named file or skill directly.
5. Only then say you don't have it — and say what you searched.

## Write protocol (memory tool only)

1. **Create the topic file first** — `write_file` → `~/.hermes/memories/<slug>.md`. Be verbose there: examples, exact commands, gotchas.
2. **Then add exactly one index line** via the `memory` tool:
   `keyword,keyword,keyword → file.md`
3. If the topic file already exists, read it first and append a section — never blind-overwrite it.

Slug recipe: lowercase, hyphen-join the first 3–4 meaningful words, drop stop words (`the`, `a`, `of`, `and`, `for`, `with`, `see`, `memories`). Cap at 60 chars.

What the plugin validates on a `memory()` write: bare `.md` target (no paths), 5–20 lowercase comma-separated keywords, no prose (comma-to-word ratio), content under the verbose threshold. Malformed lines are refused with an actionable message; arrow errors are called out separately (the format uses Unicode `→`, U+2192).

**What the plugin does NOT validate:** duplicate targets. Two index lines may point at the same file without being refused. One line per topic file is the rule, but it is enforced by discipline and by the validator script — not by the hook.

## Format rules

```
keyword,keyword,keyword → file.md
```

- **Target is a bare filename** in the same directory as the index. No `memories/` prefix, no `~/`, no absolute path.
- **Unicode arrow `→`** with a single space either side. **ASCII `->` is rejected** at two independent points in the plugin. If a validator or script objects to `→`, the validator is wrong — fix it, never downgrade the arrow.
- **One line per topic file.** No duplicate targets.
- **Keywords lowercase**, comma-separated, no spaces inside a keyword.
- **No prose, no sentences, no `§`, no parentheticals, no explanations.** Explanations belong in the topic file.
- No status reports, no "I did X" lines. Those are not memories.

**The prose detector.** Keyword lists have a high comma-to-word ratio; human language has a low one. The plugin blocks any write below 0.5. This is not a style preference — it is a mechanical prose detector, and it is why prose keeps getting rejected.

## Keyword bounds

**Floor 5, ceiling 20. Aim for 12+.** The floor forces you to think about where a file will be looked up from; the ceiling stops thesaurus sprawl.

**Never pad to reach a count.** Generic words (`use`, `make`, `file`, `work`, `data`, `info`, `url`) match nearly every query — that is a false positive, not coverage. A quota creates pressure to invent terms.

Keywords come from the file's own content — proper nouns, domain names, filenames, function names, flags, acronyms, error codes — **plus the vocabulary a user would actually use to ask about it.** Content vocabulary ≠ query vocabulary. A topic file legitimately contains jargon; a user describing a symptom says *"my camera won't respond"*, not *"PTZ endpoint returns 500"*. Include plain symptom words (`broken`, `not working`, `won't respond`, `stopped`) — these are high-signal for routing, not filler.

**Never add unverified, misspelled, or vague keywords.** A wrong keyword is worse than a missing one: it either never matches, or it matches and routes to the wrong file.

## Qualifier prefixes (user-assigned only — never self-assign)

| Prefix | Meaning |
|---|---|
| `!!` | critical — never edit this entry or its topic file without explicit user approval; propose, state the reason, stop and wait |
| `!` | pinned — never prune; content may still be updated |
| (none) | normal — ordering and pruning may move or remove it |

`!!` protects against **modification**; `!` protects against **deletion**. Different guarantees.

**Not a `!!` candidate:** anything describing a state that changes — IPs, versions, plugin enabled/disabled status, pricing, dated decisions. Volatility is a disqualifier, not a plus; pinning those freezes stale facts.

## Ordering and budget

- Entries are ranked by how often their topic file is actually read (most-accessed highest); new entries go at the top of the untagged region.
- When the character cap is exceeded, prune from the bottom. Tagged entries are never reordered and never pruned.
- **Never delete on prune.** Move, don't delete — the history of what was pruned and when must survive:
  ```bash
  mv ~/.hermes/memories/X.md ~/.hermes/old-memories/X.md.YYYYMMDD-HHMMSS
  ```

**Known flaw in pure access-ranking:** brand-new entries have no read history, so they sink to the bottom and are pruned first. If you implement a tally, tie-break by last-access date and give entries younger than a grace window (e.g. 14 days) a floor rank so they cannot be pruned before they have had a chance to be read.

## Governance — the memory-shaper plugin

Agents drift, and self-editing memory is the most dangerous surface they touch. The plugin enforces the invariants that format validation alone cannot:

- **Structural replace guard.** `old_text` must match exactly one entry line, and a replacement may never reduce the entry count by more than one. This makes whole-file clobbering structurally impossible.
- **Format enforcement.** Arrow form, target shape, keyword bounds, and the comma-to-word ratio — each violation rejected with a targeted fix message rather than passing through.
- **Write-lock without audit lockout.** Read-only operations pass through so the agent can always inspect the index it maintains, while every write vector (redirect, `tee`, `sed -i`, command substitution, `write_file`, `patch`) is blocked when it references the index.
- **No orphan detection at write time.** The validator finds orphans and dead targets; the hook does not check them on every write. Run the validator.

**Wholesale rewrite** is the one operation the hook cannot perform, and it says so in its own error message: stop and get explicit user scope approval first. With approval, set `MEMORY_SHAPER_ALLOW_REWRITE=1` (or create `~/.hermes/state/.memory_shaper_rewrite_approved`), write atomically from a script, back up first, then verify every line resolves.

## Verify the install — do not assume it works

A plugin that is installed but not enabled, or enabled but not loaded, looks identical to a working one until you test it. Run all four checks.

**1. The plugin is discovered and registers cleanly:**

```bash
hermes plugins list | grep memory-shaper          # expect: enabled
hermes plugins doctor memory-shaper               # expect: OK, no warnings
```

If `doctor` reports `unknown hook` or `manifest declares hook X but registration did not add it`, the manifest is wrong — fix it before trusting the gate.

**2. The hook actually fires through real dispatch** — not just in unit tests. The unit tests call `handle_pre_tool_call` directly and bypass Hermes' dispatch entirely, so they cannot detect a hook that never gets wired up. Test live:

```bash
hermes chat -q "Use the write_file tool to write the word TEST to ~/.hermes/memories/MEMORY.md." -Q
```

Expect a refusal naming the plugin. If the write succeeds, the hook is not loaded — check `hermes plugins list` and `/reset`.

**3. The index reaches the system prompt:**

```bash
python3 - <<'PY'
import sqlite3, os
db = os.path.expanduser("~/.hermes/state.db")
c = sqlite3.connect(db)
row = c.execute("SELECT prompt FROM system_prompts ORDER BY rowid DESC LIMIT 1").fetchone()
print("index present in system prompt:", "→" in (row[0] if row else ""))
PY
```

**4. Retrieval actually routes** — the end-to-end test, and the one most likely to fail. Ask a question that deliberately shares **no literal keyword** with any index line, then inspect the session transcript:

```bash
python3 scripts/test_retrieval.py --expect <topic-file>
```

If the transcript shows `search_files` instead of `read_file` on the expected file, the routing instruction is not reaching the model — see [Routing instructions are NOT injected for you](#routing-instructions-are-not-injected-for-you).

## Pitfalls

### `§` is banned
It was meant as a paragraph separator. It caused agents to think "paragraphs of text go here" and write prose. Zero `§` characters belong in the index.

**However:** Hermes' own memory store writes `\n§\n` as an entry delimiter between entries in some code paths. If you see `§` lines appearing on disk, that is the runtime, not the agent — and it means the newline-delimited assumption in the plugin/validator no longer matches reality. Investigate before "fixing" it, because the replace-guard's safety depends on which delimiter model is actually in force.

### Don't lower the char cap to fix compliance
The problem is never the cap size — it is prose leaking into the index. Fix the write path, not the limit.

### Scope rule for existing memory files
Before changing an existing memory file, ask which files are in scope. Blindly "rebuilding it cleaner" has destroyed original work before. Default: create a new file and show it, or ask. Only modify in place when the user says "replace" or "update the original."

### `read_file` takes the same `path` argument as `write_file`
A write-lock that matches on the `path` argument alone will block reads too, because `read_file` carries the same field. That produces the audit-lockout failure: the agent cannot read the index it is responsible for maintaining. Only path-*writing* tools (`write_file`, `patch`, `edit`) may be refused on a path match.

### Hook edits do not affect the running session
Hooks register at session start. After editing the plugin, verify with the test scripts and a fresh session — never by attempting a live call in the current one.

## Sizing reality check

A 60–70 line index (~500–600 keywords) costs roughly 350–500 tokens at session start, and that is the entire always-resident overhead. The system prompt is built once per session and cached as the prefix for every subsequent API call, so this is a once-per-session cost, not a per-turn one — it is only rebuilt after context compression. A single vector-store retrieval round-trip usually costs more than an index line costs across a whole session. If the index outgrows this range, split by profile or by tier (pinned / active / archive) rather than introducing a database.

## Reference files

| File | Purpose |
|---|---|
| [`references/diagnosing-recall-failure.md`](references/diagnosing-recall-failure.md) | Symptom → cause → fix decision tree for wrong-file, no-file, and blocked-write failures |
| [`references/memory-shaper-plugin-contract.md`](references/memory-shaper-plugin-contract.md) | Hook signature, routing rules table, constants, testing recipe |
| [`references/dynamic-memory-format.md`](references/dynamic-memory-format.md) | Quick format reference + violation gallery |
