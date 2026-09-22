# Architecture — code-level trace

How the pieces fit together inside a running [Hermes Agent](https://github.com/NousResearch/hermes-agent), verified against a v0.19 source tree.

## Components

```
┌─────────────────────────────────────────────────────────────────┐
│ Session start                                                   │
│                                                                 │
│  tools/memory_tool.py :: MemoryStore                            │
│    .load_from_disk()      reads MEMORY.md + USER.md             │
│    .format_for_system_prompt()   → frozen snapshot injected     │
│      into the system prompt. Mid-session writes update disk     │
│      but NOT the prompt — the prefix cache stays valid for the  │
│      whole session.                                             │
└─────────────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ Retrieval (model-driven, no code)                               │
│                                                                 │
│  The model scores each index line's keyword SET against the     │
│  conversation and reads matching topic files with its normal    │
│  file tools. The index block carries the routing instructions.  │
└─────────────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ Writes — two paths, both funneled into the plugin               │
│                                                                 │
│  memory tool calls:                                             │
│    plugin.handle_pre_tool_call() validates format:              │
│      · arrow lines must use Unicode → (ASCII -> is rejected     │
│        with a "wrong arrow" fix message)                        │
│      · target: bare .md filename only                           │
│      · keywords: 5–20, lowercase, comma-separated               │
│      · replace: old_text must match exactly ONE entry line;     │
│        entry count may never drop by more than one              │
│    then memory_tool.py enforces the char budget + atomic write  │
│                                                                 │
│  any other tool (write_file, patch, terminal, execute_code):    │
│    handle_pre_tool_call() blocks the call if its args reference │
│    MEMORY.md — those tools bypass every format guarantee        │
│    read-only passthrough: cat/head/tail/wc/grep/ls/stat/diff    │
│    with no redirect, pipe, tee, sed, or command substitution    │
└─────────────────────────────────────────────────────────────────┘
```

## Why middleware matters

The `memory` tool lives in Hermes' agent-loop tool set and can bypass the `pre_tool_call` hook path on some call routes. The plugin therefore registers **both** a `pre_tool_call` hook and a `tool_execution` middleware (see `register()` in `plugin.py`); both funnel into the same `handle_pre_tool_call()`, so no route skips validation.

## The replace guard

MEMORY.md is newline-delimited, one entry per line. A delimiter assumption that doesn't match the on-disk format — for example, splitting entries on some legacy separator — can yield *a single entry containing the entire file*, at which point any `old_text` matches everything and one `replace` call rewrites the file wholesale.

Two structural guards make that class of failure impossible:

1. `old_text` must match exactly one entry line (0 matches → error, >1 → error).
2. A replacement of an index line must itself be exactly one line, and the entry count may never decrease by more than one per operation.

**Design lesson:** delimiter assumptions in memory tooling must be tested against the actual on-disk format, and destructive operations need structural guards, not just format checks. Format validation answers "is this line well-formed?" — it does not answer "is this edit safe?"

## Comma-to-word ratio heuristic

Index lines are keyword lists: many commas, few spaces. Prose is the opposite. The plugin computes `commas / whitespace-separated-words` and rejects memory-tool content below 0.5. For reference, migrated index lines consistently measure ≥ 2.0, while descriptive prose measures 0.01–0.10. This catches natural-language text even when it slips under the verbose-content length threshold.

## Sizing data

- 64 index lines, ~528 keywords, 5.9 KB on disk, ~345 tokens injected per turn.
- Topic files are unlimited in individual size — they are read on demand, never injected.
- USER.md is kept as a separate, small, always-in-context block.

## Lifecycle: the access watchdog

`scripts/dynmem-watchdog.py` automates ordering and eviction. Run on a
schedule (daily is plenty; it is silent when it has nothing to report):

```
 state.db tool-call history        memories/.access-tally.json
 ────────────────────────  tally    ─────────────────────────────
   incremental scan,           →     {file: {reads, last}}
   one access per message            (sidecar — never in the index)
                                          │
                                          ▼
 MEMORY.md untagged lines          sort hot-first, in place
 ──────────────────────────        (!! / ! never move)
                                          │
                              over 95% of char cap?
                                          ▼
 memories/X.md  ──move──▶  memories/archived memories/X.md
 its line      ──move──▶  memories/archived memories/archived-memories.md
 (backup:      ──────▶   memories/archived memories/MEMORY.md.bak-<ts>)
 ```

Three properties make this safe to leave running:

1. **Move, never delete.** An archived topic file keeps its plain `.md`
   name and its index line moves verbatim beside it, so the archive is a
   normal keyword-searchable index — step 2 of the retrieval order, ahead
   of any deep fallback.
2. **Structural freeze.** The script only permutes untagged entry lines
   among the slots they already occupy. Header, tagged block, the template
   line, and every malformed line are anchors it cannot touch. A
   character-multiset check of the file before/after each apply is part of
   development testing for exactly this reason.
3. **Grace window.** Files younger than 14 days, or accessed in the last
   14 days, are never archive candidates — which fixes the known flaw of
   pure access-ranking (new entries have no history and would sink
   straight to the eviction queue).

The archive index is regenerated from the files actually present in the
archive directory on every run, so it cannot drift, and a restored file's
line drops out automatically on the next pass.

## Configuration

The memory directory resolves via `HERMES_HOME` at runtime, never as an import-time constant. A cached module-level path goes stale when an agent profile switches after first import — a subtle failure that only shows up in multi-profile setups, so the path lookup is deliberately re-evaluated on every call.
