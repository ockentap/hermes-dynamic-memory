# Diagnosing recall failure

Symptom → cause → fix. Run these in order; each one rules out a whole class of
problem before you touch anything.

The key insight: **every failure mode in this system is silent.** A dead index
line, an unloaded hook, and a missing routing instruction all produce the same
observable behaviour — the agent answers without the memory, or reaches for
`search_files` instead of the topic file. Nothing errors. You have to test
deliberately.

## Step 0 — establish what "working" looks like

Before diagnosing, confirm the four-layer chain is intact:

```
MEMORY.md on disk  →  injected into system prompt  →  model routes  →  read_file on topic file
      1                        2                            3                  4
```

Each layer can fail independently, and each has its own test. Work down.

## Layer 1: is the index file correct?

**Symptom:** anything at all downstream.

```bash
python3 scripts/verify_index.py ~/.hermes/memories/MEMORY.md
```

Catches malformed lines, bad arrows, dead targets, keyword-count violations, and
orphaned topic files (in both directions). Exit 0 means this layer is fine.

**If it reports orphans:** a topic file with no index line is unreachable content.
Add a line, or move the file out of `memories/` if it is archive material.

**If it reports dead targets:** the line points at a file that doesn't exist. Fix
the filename or delete the line.

## Layer 2: does the index reach the model?

**Symptom:** the agent behaves as if memory is empty.

The index is injected as a frozen snapshot at session start. It is not re-read
per turn, so a write made mid-session is invisible until the next session.

```bash
python3 - <<'PY'
import sqlite3, os
c = sqlite3.connect(os.path.expanduser("~/.hermes/state.db"))
row = c.execute("SELECT prompt FROM system_prompts ORDER BY rowid DESC LIMIT 1").fetchone()
p = row[0] if row else ""
print("length:", len(p))
print("index present:", "→" in p)
i = p.find("→")
print(repr(p[max(0, i-300):i+120]) if i > 0 else "(no arrow found)")
PY
```

Note: `sessions.system_prompt` is often empty; the prompt lives in the
`system_prompts` table keyed by hash. Join via `sessions.system_prompt_hash` if
you need the prompt for a *specific* session.

**If absent:** check that `MEMORY.md` exists (not `memory-index.md`, not a
`.txt`), that the path is `~/.hermes/memories/`, and that `memory.memory_enabled`
is true. A profile switch changes `HERMES_HOME` — verify you are looking at the
right profile's directory.

## Layer 3: does the model route?

**Symptom:** the agent finds the right answer, but by `search_files` rather than
by reading the indexed file. Or it answers without memory at all.

This is the most commonly missed failure, because **the answer is often correct.**
Brute-force filesystem search finds the file at one or ten topic files. It does
not scale to a hundred, and it silently defeats the design's entire purpose.

**Test:** ask a question sharing **no literal keyword** with the index, then read
the transcript.

```bash
hermes chat -q "My shots have been coming out sour lately." -Q
# then inspect the last session's tool calls:
python3 scripts/test_retrieval.py --last --expect coffee-log.md
```

**If the transcript shows `search_files`:** the routing instruction is not reaching the model. Stock Hermes does **not** attach routing instructions to the memory block — it renders the index under a `MEMORY (your personal notes)` header and stops. Supply the rule via the skill, your personality file, or `config.yaml`:

> Your memory index is a routing table, not a summary. When the conversation
> touches several keywords from one line — or an obviously related term the line
> doesn't spell out — read that file in full before answering. Prefer the line
> whose keyword set matches best overall, not the first line sharing a single
> word.

**Caution — not every `search_files` call is a routing failure, and the
distinction is easy to get wrong:**

| Pattern | Meaning |
|---|---|
| Search returns **hits**, runs **before** the read | Real failure — the file was located by brute force |
| Search returns **nothing**, runs before the read | Wasted speculation; the filename came from the index line |
| Search runs **concurrently** with the read (same step) | Enumeration, not a lookup — the agent already had the path |

Only the first is a routing failure. `scripts/test_retrieval.py` implements
exactly this distinction; read its output rather than eyeballing a transcript.

Note also that `search_files` frequently returns `total_count: 0` for a file that
plainly exists on disk — observed repeatedly against files under
`~/.hermes/memories/` while `read_file` on the same path succeeded in the next
step. Do not treat an empty search result as evidence the file is missing.

**If the model reads the wrong file:** it is a keywords problem, not a routing
problem. The losing line's keyword set is too dense or too generic for the query.
Re-read the keyword hygiene rules — a wrong keyword routes confidently to the
wrong place, which is worse than no keyword at all.

**If the model answers without any tool call:** it either judged the index line
sufficient (fine for trivia, wrong for detail) or never recognised the query as
memory-relevant. The routing instruction fixes the second case.

## Layer 4: does the topic file answer?

**Symptom:** the agent reads the correct file and still gives a thin answer.

The file is stale, or was written as a stub. Topic files are the verbose tier —
if the detail isn't there, the two-tier split has nothing to retrieve. Rewrite
the file, then update its keywords in the same pass if the content changed
conceptually.

## Write-path failures

Separate class: the agent tried to save something and got refused.

### Everything is refused, including reads

**Symptom:** `read_file` on the index is blocked with "write-locked".

**Cause:** the write-lock matches on the `path` argument. `read_file` carries the
same `path` field as `write_file`, so a path-only check blocks reads too. This is
the audit-lockout class — the agent cannot inspect the index it maintains.

**Fix:** only path-*writing* tools (`write_file`, `patch`, `edit`,
`create_file`) may be refused on a path match. Add a regression case to
`scripts/test_hook_cases.py` so it cannot come back.

### Plain `ls` / `stat` / `grep` is refused

**Cause:** the read-only predicate requires *no shell operators at all*. A
command like `ls -la ~/.hermes/memories/ 2>&1; echo "---"; stat ...` contains
`;` and `2>&1`, so it is classified as a write.

**Fix (either):** widen the predicate so `;`-separated read-only pipelines are
recognised, or split the command. Widening is better — the current rule pushes
agents into workarounds, and an agent that cannot inspect the memory directory
cannot diagnose it either.

### Prose is refused

Expected. That is the comma-to-word ratio detector working. Write the detail to
a topic file with `write_file` (not locked), then add a one-line keyword entry.
Do not try to shorten prose into a "keyword-shaped" sentence to sneak past the
check — the ratio will fail again, and if it passes you have polluted the index.

### Verbose content is refused

Also expected, above the 140-char threshold. Same fix: topic file, then pointer.

### Wholesale rewrite is refused

Working as designed. The hook cannot safely perform a full rewrite and says so.
Get explicit user scope approval, then set `MEMORY_SHAPER_ALLOW_REWRITE=1` (or
create `~/.hermes/state/.memory_shaper_rewrite_approved`), back up first, write
atomically from a script, and verify every line resolves afterwards.

## Plugin-layer failures

### Plugin installed but not enabled

```bash
hermes plugins list | grep memory-shaper   # "not enabled"?
hermes plugins enable memory-shaper
```

Enabling takes effect **next session**. Enablement alone also prompts for tool-
override permission; declining is correct for this plugin (it hooks rather than
replaces tools).

### Enabled but the hook never fires

`hermes plugins doctor <name>` reports what actually registered:

```
OK: runtime discovery, manifest parsing, import, and registration passed
registrations: 0 tool(s), 1 hook(s)
```

- `unknown hook 'X' in provides_hooks` → the manifest names a hook that isn't
  real. Hook names must come from the framework's valid set; `tool_execution` is
  middleware, registered via `ctx`, not a declarable hook.
- `manifest declares hook X but registration did not add it` → manifest and
  `register()` disagree. Make them match.
- `registration adds hook X not listed in provides_hooks` → warning only, but
  fix the manifest so `doctor` is clean.
- A trailing `---` in `plugin.yaml` makes the whole manifest unparseable, and
  discovery fails with "found no valid plugin manifest". YAML frontmatter opens
  with `---`; it does not close with one.

**Unit tests cannot catch this.** `scripts/test_hook_cases.py` calls
`handle_pre_tool_call` directly, bypassing Hermes' dispatch — it passes happily
while the hook is not wired up at all. Always confirm with a live session.

### Hook fires, then stops working

Hook errors disable the gate for the session. Check `~/.hermes/logs/errors.log`
and `agent.log`. A `TypeError` from an unexpected kwarg is the classic cause —
the handler must tolerate unknown kwargs (`**_unknown`), because the dispatcher
injects telemetry fields.

## The three silent killers

Ranked by how long they go unnoticed:

1. **No routing instruction.** Answers look right, mechanism is brute force. Only
   a transcript inspection reveals it.
2. **Orphaned topic files.** Content exists, nothing points at it. Only a
   validator reveals it.
3. **Unloaded hook.** Format drifts freely, and nothing complains until the
   index is already corrupt.

Test for all three explicitly after any install, upgrade, or profile change.
None of them produce an error message.
