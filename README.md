# hermes-dynamic-memory

**Dynamic memory for AI agents: a ~400-token keyword index lives in the system prompt, verbose topic files stay on disk, and a plugin keeps the index well-formed.**

A production-tested pattern for personal agent memory — no vector database, no embedding calls, no retrieval infrastructure. Just an index file and a convention.

---

## Benchmark: complex memories

Most memory benchmarks count how many facts survive. That is the easy question. The
hard one is whether **structured, detailed memories** survive — a migration policy
with its exceptions and named approver, an incident-severity definition with timing
thresholds, a deploy order with canary gates. These are the memories a lossy summary
destroys while keeping the headline.

Six such memories, each probed for every detail it contained. 30 probes per system.
Clean containers, one fresh session per question, memory as the only possible source.

**Conditions:** model `deepseek 4.1 flash` (provider `deepseek`; configured as
`deepseek-chat`), Hermes v0.21.3, native cap 2,200 chars, 2026-09-19. The model is part
of the result — it prefers local filesystem evidence over injected memory, which works
*against* dynamic memory in these numbers. The same conditions are stamped into every
raw results file.

| | Native memory | Dynamic memory |
|---|---|---|
| detail probes answered correctly | **11 / 30** | **30 / 30** |
| complex memories held | 2 of 6 | **6 of 6** |
| resident cost to hold them | 1,615 chars | **503 chars** |

### Native memory does not degrade — it cuts off

<img src="docs/charts/detail-recall.svg" alt="Detail recall: native 11/30, dynamic 30/30" width="640">

Native kept 2 of 6 complex memories and **refused the other 4 outright**. On the two
it held, it recalled **every detail — 11 of 11**, including the named approver and
the 7-day snapshot rule. On the four it could not store, it recalled **0 of 19**.

Not degraded. Zero. A memory is either fully present or entirely absent, and which
one depends only on the order it arrived in.

### Capacity at an equal resident budget

<img src="docs/charts/capacity.svg" alt="Complex-memory capacity: native 2.7, dynamic 16.8" width="640">

With 12 keywords per entry — a **stated assumption**, since the real index in this
benchmark averaged 7 keywords and 82 chars per line. The 12-keyword model gives
~131 chars per index line and is therefore the conservative case:

| | complex memories in 2,200 chars |
|---|---|
| Native memory | **2.7** (measured) |
| Dynamic memory, 12 keywords/entry | **16.8** (projected) |
| Dynamic memory, as actually measured (7 kw/entry) | **26.8** |
| | **6.2× more** at the conservative 12-keyword rate |

### Resident cost

<img src="docs/charts/resident-cost.svg" alt="Resident memory-block characters vs memories held" width="640">

Native's resident block is flat-capped at 2,200 chars from the 4th memory onward —
adding more memories adds cost with no added capability. Dynamic's index grows at
~130 chars per memory and stays inside the same budget until 16.

### What this means

Native's limit is **count, not depth**. It holds a few memories perfectly and loses
everything past that, with no way to prioritise — the migration policy survived only
because it was written first. Dynamic memory trades a keyword lookup for the ability
to keep far more, in full detail, at a fraction of the resident cost.

**Read the full method, including limitations:** [`docs/complexity.md`](docs/complexity.md) ·
[`docs/cohort-50.md`](docs/cohort-50.md) · [`docs/compression.md`](docs/compression.md)

**Verify it yourself:** [`benchmarks/`](benchmarks/README.md) contains the fixtures,
scripts and raw transcripts. Re-score the committed answers with no API key and no
containers:

```bash
python3 benchmarks/scripts/run_complexity.py --verify-only
# native  : 11/30
# dynamic : 30/30
```

An independent clean re-run reproduced dynamic exactly (30/30) and native in shape
(10/11 stored, 0/19 refused), with the variance traced to reconstruction rather than
recall — see [`benchmarks/REPRODUCTION.md`](benchmarks/REPRODUCTION.md).

---

## The pattern

```markdown
# Memory Index — keyword,keyword,keyword → file.md
!!how,write,memory,format,keyword,entry,template → how-to-write-memories.md
!project,deploy,release,pipeline,staging,rollback → deploy-pipeline.md
java,springframework,jvm,garbagecollection,heap,profiling,jmx → java-performance.md
javascript,typescript,npm,bundler,webpack,vite,node,lint → js-toolchain.md
database,postgres,index,query,explain,migration,vacuum → postgres-notes.md
```

Every line is a pointer. `java-performance.md` can be as long and detailed as it needs to be — it costs nothing until the conversation actually touches JVM internals.

---

## The problem with always-on memory

Most agent memory systems (including the default `MEMORY.md` in Hermes, Claude Code, and OpenClaw) inject one curated memory file into every session. It works well until it doesn't:

- **Budget pressure.** Every fact competes for the same character cap. You end up deleting useful history, or truncating it silently.
- **Uniform cost for non-uniform value.** A recipe you need once a month costs exactly as much context as an API quirk you hit daily.
- **Unbounded growth, bounded context.** Memory that's genuinely useful over years cannot fit in a prompt that's rebuilt every turn.

The fix isn't a bigger prompt or a database. It's splitting memory into **a tiny always-resident index** and **unlimited on-demand detail**.

## Architecture

Two tiers, one index line per topic:

```
                  session start
                       │
         ┌─────────────▼──────────────┐
         │ MEMORY.md  (~400 tokens)   │  injected into the system prompt
         │ keyword,keyword → file.md  │  as a frozen snapshot
         └─────────────┬──────────────┘
                       │  model evaluates the conversation
                       │  against the keyword SETS
         ┌─────────────▼──────────────┐
         │  read the best-matching    │
         │  topic file(s) in full     │
         └─────────────┬──────────────┘
                       ▼
   ~/.hermes/memories/<slug>.md    verbose markdown, unlimited size,
   (as many files as you need)     written with normal file tools,
                                   never in context unless routed to
```

**Design rules**

- **One line per topic file** — 5–20 lowercase comma-separated keywords. The floor forces you to think about where a file will be looked up from; the ceiling stops keyword sprawl.
- **Qualifier prefixes** (`!!` critical, `!` pinned) are user-assigned only — the agent never tags its own entries. Tagged lines are never pruned or reordered.
- **Ordering is access-driven.** Most-read topics float to the top; when the index hits its character cap, pruning happens at the bottom.
- **Pruning archives; it never deletes.** The evicted file moves to `memories/archived memories/` under its plain `.md` name and its index line moves verbatim into `archived-memories.md` there — a keyword-searchable index one directory deep. See [`scripts/dynmem-watchdog.py`](scripts/dynmem-watchdog.py).
- **Keywords are maintained with the file.** Adding a concept to a topic file without adding matching keywords creates content nothing can ever reach.

## Retrieval: set-level matching with model-side fuzz

This is where the approach differs from both naive keyword lookup and embedding RAG.

**1. The whole keyword set is scored, not individual keywords.**

The conversation says *"the java script for the build is broken."* Per-keyword matching hits `java` in the JVM line and `javascript` in the toolchain line and ranks them equally — the agent reads the wrong file. Set-level matching sees that the toolchain line's full set (`javascript,typescript,npm,bundler,vite,node,lint`) is denser and more specific here than the JVM line's (`java,jvm,garbagecollection,heap,profiling,jmx`), and routes correctly. That entire collision class disappears.

**2. The model does the semantic matching, over a literal index.**

*"My laptop's fans won't stop spinning at idle"* contains no `fan` keyword anywhere in the index. The model — already in the loop — makes the jump fans → `thermal` and reads the hardware file before answering. Fuzziness comes from the model, not an embedding engine: no vector store, no ANN index, no similarity threshold to tune, no API cost, nothing to keep in sync.

The index block carries the routing instruction in the deployed configuration: *treat these lines as a routing table; prefer the line whose keyword set matches best overall; follow related terms that aren't spelled out in the line.* See [Making retrieval actually fire](#making-retrieval-actually-fire) for where that instruction lives and why it matters.

**What you trade away.** Recall depends on the agent knowing to treat the index as a routing table, and on index hygiene — which is what the enforcement layer below is for.

**Important:** stock Hermes injects the index block as-is, with no routing instructions attached. It renders your `MEMORY.md` under a `MEMORY (your personal notes)` header and stops there. The routing instruction therefore has to come from somewhere you control — the [`skill/`](skill/) file is the supported place for it (see [Making retrieval actually fire](#making-retrieval-actually-fire) below). Without it, a capable model will often still find the right file, but by searching the filesystem rather than by routing from the index — which is slower and defeats the point.

There is no fallback search in the core design. The one thing that is part of the design is the **archive index** (`memories/archived memories/archived-memories.md`): when the access watchdog evicts an entry, its keyword line moves there verbatim and its topic file keeps its name beside it — so yesterday's curated memory is still keyword-searchable forever. Anything deeper (session search, vector stores) you can run alongside, but keep it separate rather than coupling it to the index.

## Making retrieval actually fire

Stock Hermes does **not** attach routing instructions to the memory block. It renders your `MEMORY.md` into the system prompt under a `MEMORY (your personal notes)` header and nothing more. The index arrives as a bare list of lines with no indication that they are pointers.

A capable model will often work it out anyway — but in testing it did so by *searching the filesystem* for a matching filename rather than by routing from the index. That is the failure mode worth understanding: the answer came out right, but the mechanism was brute force, and it would not scale to a few hundred topic files.

The fix is to state the contract where the model will always see it. Two options:

1. **Skill file (recommended).** The [`skill/`](skill/) directory ships the routing rule in its retrieval section. Install it as described in [Install](#install) and the instruction loads with the skill.
2. **Personality / system prompt.** If you don't load the skill, put the rule into your personality file or `config.yaml` so it is present in every session:

   > Your memory index is a routing table, not a summary. When the conversation touches several keywords from one line — or an obviously related term the line doesn't spell out — read that file in full before answering. Prefer the line whose keyword set matches best overall, not the first line sharing a single word.

Verify it works by asking a question that deliberately shares **no** literal keyword with the index and then checking the session transcript for a `read_file` on the expected topic file. If you see `search_files` instead, the routing instruction isn't reaching the model.

## Governance: the memory-shaper plugin

A self-editing memory is both the feature and the failure mode. Left unguarded, an agent can quietly destroy the index it depends on. The plugin ([`plugin/memory-shaper/`](plugin/memory-shaper/)) hooks the tool-call paths and enforces structural guarantees:

| Failure mode | The guard |
|---|---|
| Index clobbering | A `replace` must match **exactly one** entry line (0 or >1 → refused), and a replacement may never reduce the entry count by more than one |
| Format drift | Lines are validated on write: Unicode `→` only, bare `*.md` targets, 5–20 lowercase keywords, no prose. Rejections carry an actionable fix message instead of silently passing |
| Path tricks | Index targets must be bare filenames — no paths, no `../` escapes |
| Write-vector bypass | `write_file`, `patch`, shell redirects, `tee`, `sed -i`, and command substitution all bypass the `memory` tool's guarantees, so **all** non-`memory` tools are blocked when their arguments reference the index |
| Audit lockout | Read-only tools and commands pass through, so the agent can always inspect the file it maintains. This includes `read_file`, which takes the same `path` argument as `write_file` — blocking on a path match alone would refuse reads of the index (a bug fixed in 1.4.2; the test suite now guards it) |
| Orphan rot | The validator flags topic files with no index line (unreachable content) and index lines pointing at missing files, on every candidate write |

See [`examples/`](examples/) for a runnable demo index and a worked retrieval walkthrough, and [`scripts/`](scripts/) for the validator and hook test suite.

## What it costs

| | Tokens |
|---|---|
| Session start (index block, ~60 lines / ~500 keywords) | ~350–500 |
| Per retrieval | one file read — a few hundred to a few thousand, only when routed |
| Retrieval infrastructure | zero |

That always-on index block is the **entire** overhead. As a comparison point: a single vector-DB retrieval round-trip usually costs more than an index line costs across an entire session. For personal-scale memory (tens to hundreds of files, not millions of documents), a database loses on cost *and* on transparency — the index is plain text you can read and edit by hand.

**Scale, honestly:** this is designed for personal agent memory — tens to low hundreds of topic files. Beyond that, split by profile or by tier (pinned / active / archive) rather than reaching for a database.

## Install

1. **Plugin** — copy `plugin/memory-shaper/` into `~/.hermes/plugins/` and enable it in `config.yaml`. Paths resolve via `HERMES_HOME` (default `~/.hermes`). Requires a Hermes build with pre/post tool-call hooks and `tool_execution` middleware.
2. **Skill** — copy `skill/` to `~/.hermes/skills/system-administration/dynamic-memory/` so the agent learns the write protocol and format rules.
3. **Adopt the format** — restructure `MEMORY.md` into one `keywords → file.md` line per topic, moving the verbose content into topic files. Then validate:
   ```bash
   # index and topic files side by side (the normal layout)
   python3 scripts/verify_index.py ~/.hermes/memories/MEMORY.md
   
   # or validate a candidate index against the live memory directory
   python3 scripts/verify_index.py ./candidate-MEMORY.md --memdir ~/.hermes/memories
   ```
   It exits 0 when every line is well-formed, every target exists, and no topic file on disk is unreachable.
4. **Test the hooks** — the unit suite checks the *logic*; it calls the handler directly and bypasses Hermes' dispatch, so it cannot detect a hook that never loads.
   ```bash
   python3 scripts/test_hook_cases.py      # logic: reads pass, every write vector blocks
   ```
   Then confirm the *wiring* against a live session:
   ```bash
   hermes plugins list | grep memory-shaper     # must say "enabled"
   hermes plugins doctor memory-shaper          # must say OK, with no warnings
   hermes chat -q "Use write_file to append the word TEST to ~/.hermes/memories/MEMORY.md."
   # expect a refusal naming memory-shaper — if the write lands, the hook is not loaded
   ```
5. **Verify retrieval end-to-end** — the step most likely to be skipped, and the one that catches the silent failure. Ask a question sharing **no literal keyword** with the index, then check the transcript:
   ```bash
   python3 scripts/test_retrieval.py --last --expect <topic-file>.md --check-prompt
   ```
   It distinguishes routing from brute-force search, including the three cases where a `search_files` call is *not* a failure. If it reports the file was located by search, your routing instruction is not reaching the model — see [Making retrieval actually fire](#making-retrieval-actually-fire).
6. **Try the demo first (optional)** — the example index in this repo validates clean, so you can see the target layout before restructuring your own:
   ```bash
   python3 scripts/verify_index.py examples/memories/MEMORY.md
   # 7 lines OK, 0 bad lines, 0 orphaned files
   ```
7. **Automate the lifecycle (optional)** — `scripts/dynmem-watchdog.py` tallies
   topic reads from the agent's session database, keeps untagged lines sorted
   most-read first, and when the index passes 95% of its char cap archives the
   least-read entries to `memories/archived memories/` (plain `.md`, searchable,
   nothing deleted). Stdlib only; run it on any scheduler, silently:
   ```bash
   python3 scripts/dynmem-watchdog.py --dry-run    # see what it would do
   ```

## Troubleshooting

The skills ship a full symptom → cause → fix decision tree at [`skill/references/diagnosing-recall-failure.md`](skill/references/diagnosing-recall-failure.md). Every failure mode in this system is silent — a dead index line, an unloaded hook, and a missing routing instruction produce identical observable behaviour — so the reference exists to make them distinguishable. The three that go unnoticed longest:

1. **No routing instruction.** Answers look correct because the model brute-forces the file. Only a transcript inspection reveals it.
2. **Orphaned topic files.** Content exists; nothing points at it. Only the validator reveals it.
3. **Unloaded hook.** Format drifts freely until the index is already corrupt.

If you hit a failure the decision tree does not cover, please open an issue with the transcript excerpt — that is how this list gets built.

## Porting to other agents

The format is one file plus a convention — nothing here is Hermes-specific. The minimum viable version is *an index file with `keywords → file.md` lines, plus a system-prompt instruction to read the best-matching file before answering*. The plugin is hardening, not a requirement.

- **Claude Code / auto-memory** — keep `MEMORY.md` as the index, topic files beside it. Claude Code already reads the index at startup and reads files on demand; the change is making index lines keyword sets rather than descriptions.
- **OpenClaw** — the same two-file shape applies; let the index route instead of a hybrid vector/BM25 layer (or run both).
- **OpenHands** — keyword-triggered skills already use trigger-word frontmatter; a topic-file memory index works the same way at directory scope.
- **Any file-tool agent** — two files, one convention, no dependencies.

## Prior art, and what's different here

The pattern class exists and pieces of it are documented elsewhere. Honest positioning:

- **OpenHands keyword-triggered skills** — files with `triggers:` frontmatter loaded on literal keyword match. Same routing idea, but per-skill triggers, no index file, no set scoring, no governance.
- **Claude Code auto-memory** — an index file loaded at startup with topic files read on demand. Index lines are one-line *descriptions*, not keyword sets, so matching is left entirely to the model's reading of prose.
- **pi-memory-tree** — hierarchical keyword index to detail files. Structurally the closest match; no set-level matching, no enforcement layer.
- **A-MEM / MemInsight** (academic) — LLM-generated keywords and tags per memory note, but with embedded/vector retrieval and graph linking rather than a literal always-resident index.
- **mem0, Cognee, Letta/MemGPT, Zep** — database-backed memory layers. A different point on the curve: infrastructure for app-scale memory, versus a zero-dependency format for personal agents.

**What this project adds:** (1) set-level keyword evaluation against the conversation, which eliminates single-keyword collisions; (2) model-side associative matching over a *literal* index, so no embeddings are involved anywhere; (3) a hook-enforced governance layer that treats the index as a locked artifact; (4) consolidated, tested tooling — validator, hook test suite, and skill — that you can drop into a running agent today.

If you know of prior art we've missed, please open an issue.

## Compatibility with Hermes' built-in memory

This project sits on top of Hermes' native memory file, which means **Hermes updates can break it.** Everything below was verified against **Hermes v0.21.3** and is the reason this section exists. Read it before upgrading.

**Pin your Hermes version, and re-run the checks after any upgrade.**

### What the native layer does that this project has to work around

| Behaviour | Where | Consequence |
|---|---|---|
| `ENTRY_DELIMITER = "\n§\n"` is hardcoded | `tools/memory_tool_store.py:23` | Every write re-inserts a bare `§` line between entries. It is not configurable and **no plugin can remove it** — the join happens after hooks return. |
| The resident block ships with **no routing instruction** | `_render_block()` | Hermes emits a header, a usage percentage, and the entries. Nothing tells the model the lines are pointers. Without an explicit routing rule (this skill, or your personality file) the model may find files by searching the filesystem instead — correct answers, wrong mechanism, no scaling. |
| The cap is **2,200 chars** by default | `cli-config.yaml.example:942` | Roughly 800 tokens. Reached fast; the tool then *refuses* new entries and tells you to consolidate. Content is lost or compressed, silently, as a normal part of use. |
| `read_file` and `write_file` share the `path` argument | tool schemas | Any plugin enforcing a write-lock by path alone will also block reads, locking the agent out of auditing its own index. Fixed in memory-shaper 1.4.2; relevant if you write your own plugin. |
| Entries are joined with `§` **in the prompt too** | `_render_block()` | The model sees entries separated by a `§` token while the file on disk shows a line break. Two views of one file disagreeing is a standing invitation to confusion. |

### What this means when Hermes upgrades

Any of the five could change without notice. In particular:

- If `ENTRY_DELIMITER` changes, the `§` lines stop appearing — harmless, the validator already treats them as optional.
- If Hermes **adds** routing instructions to the memory block, part of the skill's job becomes redundant. Harmless.
- If Hermes adds a **detail tier of its own**, this project's reason to exist shrinks. That would be a good outcome, not a bad one.
- If the **memory tool's file format changes**, the write-lock and validator may start rejecting valid content. This is the failure mode to watch, and the one that would need a fix.

### After upgrading Hermes, run these

```bash
hermes plugins doctor memory-shaper                 # manifest + hook still register
python3 scripts/test_hook_cases.py                  # hook logic unchanged
python3 scripts/verify_index.py ~/.hermes/memories/MEMORY.md
python3 scripts/test_retrieval.py --last --expect <a-topic-file>.md
```

If `verify_index.py` starts reporting failures on an index it previously passed, check the `§` handling first — the separator count line in its output tells you which delimiter model is currently in force.

### If a future Hermes makes this redundant

We would call that success. The two things worth borrowing from this project regardless of its own fate are: **an always-resident keyword index with verbose detail kept out of the prompt**, and **enforcement at the hook layer rather than in documentation**. Both are compatible with any memory backend.

## Repo layout

```
plugin/memory-shaper/        the enforcement plugin (drop into ~/.hermes/plugins/)
skill/                       the dynamic-memory skill + diagnostic references
scripts/verify_index.py      index validator (arrows, targets, keyword bounds, orphans)
scripts/dynmem-watchdog.py   access tally, hot-first reorder, archival prune (move, never delete)
scripts/test_hook_cases.py   hook logic test: reads pass, every write vector blocks
scripts/test_retrieval.py    did retrieval route from the index, or brute-force search?
examples/memories/           synthetic demo index + topic files (fully fictional),
                             incl. archived memories/ with its searchable archive index
examples/demo-retrieval.md   worked demo: set matching and associative jumps
docs/architecture.md         architecture deep-dive (code-level trace)
docs/benchmark.md            native vs dynamic: resident cost + retrieval, with limitations
docs/benchmark-raw-results.json  raw transcripts behind the benchmark
docs/compression.md          measured compression + entry-capacity numbers
docs/cohort-50.md            50-memory cohort: clean run, 58% vs 92%, with the two invalid runs documented
docs/cohort-50-raw-results.json  raw answers for all 50 questions
docs/complexity.md           complex structured memories: native loses them whole, 37% vs 100%
docs/complexity-raw-results.json  raw answers for all 30 detail probes
docs/nested-memories-future.md    future concept: nested memory routing + its blockers
NOTICE                       attribution requirements for redistributors
```

**Note on the benchmark:** [`docs/benchmark.md`](docs/benchmark.md) is written to
be read sceptically, and it opens by documenting an experiment that was **wrong**
— asking general technical questions the model could already answer from
pretraining, which measures the model rather than the memory.

Three corrected experiments, using invented private facts that exist only in the
memory files:

- **Direct questions, 3 topics** → tie, 12/12 both.
- **Fuzzy prompts sharing zero keywords with the index** → tie, 12/12 both.
- **8 topics (past the 2,200-char cap)** → stock memory does not refuse, it
  **consolidates**: one entry truncated mid-sentence, one fact dropped, while the
  keyword index kept all 8 topics fully answerable at ~1/8 the resident cost.

The defensible claim is **equivalent retrieval plus a much higher ceiling before
information is lost** — not that dynamic memory answers better. The size at which
loss becomes materially harmful is not yet measured.

The examples are **synthetic** — invented topics (JVM tuning, a frontend build
chain, home network admin) chosen to demonstrate the two hard cases: a literal
naming collision (`java` vs `javascript`), and a conversation term that appears
in no index line at all (fans → thermal). No real memory data is published here.

## Limitations

- Routing quality is model-dependent: the index instructs, it doesn't force. (The plugin *does* force format compliance.)
- Keyword choice is the craft. Vague keywords cost more than missing ones; the 5-keyword floor is a forcing function.
- No standardized benchmark numbers (LoCoMo and similar) yet — this is engineering from production use, not a research claim. PRs welcome.
- Single-user, single-machine by design. Multi-agent sharing works through profile separation, not concurrent writes.
- Validated primarily on Linux; the plugin and scripts are plain Python and stdlib-only, so other platforms should work but are untested.

## Contributing

Issues and PRs welcome — especially porting notes for other agent frameworks,
validator edge cases, and benchmark results.

## Attribution

This project is **hermes-dynamic-memory by ockentap** —
https://github.com/ockentap/hermes-dynamic-memory

Licensed under the Apache License, Version 2.0. If you redistribute it, or a
derivative work based on it, you must:

- retain the [LICENSE](LICENSE) and [NOTICE](NOTICE) files, and
- credit the original project in your documentation, about screen, or credits
  where other third-party notices appear.

You may use this software commercially and in closed-source products. You may
not present it, or a substantial portion of it, as your own original work, and
the project name and the identifier "ockentap" may not be used to endorse or
name derived products without written permission (Apache-2.0, Section 6).
See [NOTICE](NOTICE) for the full text.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
