# memory-shaper plugin contract

The hook-layer enforcer for the dynamic-memory architecture. Location:
`~/.hermes/plugins/memory-shaper/plugin.py`.

**Architecture it enforces:** the index file is a flat keyword list
(`keyword,keyword → file.md`, bare filename targets, same directory). There is
no separate `memory-index.md` — it was removed, and referencing it causes drift.

## Why a hook rather than documentation

Documentation alone does not hold. An agent that edits its own memory will
eventually write prose into the index, use the wrong arrow, or clobber the file
wholesale — not from malice, but because format rules stated in a skill are one
context window away from being forgotten. Enforcement belongs at the tool-call
layer, where it cannot be skipped.

## Hook signature

Registered twice, because the two dispatch paths differ:

```python
def register(ctx):
    ctx.register_hook("pre_tool_call", handle_pre_tool_call)
    ctx.register_middleware("tool_execution", handle_tool_execution_middleware)
```

**Why both:** `pre_tool_call` fires for `terminal`/`write_file`/`patch`/
`execute_code` but **not** for `memory` — `memory` is in the agent-loop tool set
and dispatches through the middleware chain instead. Both paths funnel into
`handle_pre_tool_call`, so the rules live in one place.

`handle_pre_tool_call` returns `{}` or `None` for passthrough, or
`{"action": "block", "message": "..."}` to refuse. The middleware returns a JSON
error envelope (the model sees a failed tool call).

The signature must tolerate unknown kwargs (`**_unknown`) — the dispatcher
injects telemetry kwargs, and a `TypeError` there silently disables the gate.

## Routing rules

| Tool / call | Decision |
|---|---|
| `memory(target='user', ...)` | passthrough — USER.md is not locked |
| `memory(action='remove', ...)` | passthrough — deletes are safe |
| `memory(add/replace, target='memory', content is prose)` | **BLOCK** — comma/word ratio < 0.5 |
| `memory(add/replace, target='memory', content > 140 chars)` | **BLOCK** — verbose content |
| `memory(add/replace, target='memory', short keyword line)` | passthrough |
| `write_file` / `patch` / `edit` with `path` == index path | **BLOCK** |
| `read_file` with `path` == index path | passthrough — reads are always allowed |
| `terminal` whose command writes to the index | **BLOCK** |
| `terminal` read-only (`cat`/`head`/`wc`/`grep`/…) on the index | passthrough |
| `execute_code` whose code mentions the index | **BLOCK** |

**The `path` field is shared between `read_file` and `write_file`.** A check that
refuses any tool carrying the index path will refuse reads as well, locking the
agent out of auditing its own index. Only path-*writing* tools may be classified
by path alone.

## Constants

```python
VERBOSE_THRESHOLD = 140       # chars above which content is "verbose"
MIN_COMMA_WORD_RATIO = 0.5    # below this, content is prose not keywords
ARROW_LINE_RE = re.compile(r"^[a-z0-9,\s-]+\s*→\s+~?/?[\w./~%-]+\.md\s*$", re.I)
ASCII_ARROW_LINE_RE = re.compile(r"^[a-z0-9,\s-]+\s*->\s+~?/?[\w./~%-]+\.md\s*$", re.I)
```

The comma/word ratio is the load-bearing heuristic. Keyword lists separated by
commas have a high ratio (≥ 2.0 empirically); human prose has a low one
(0.01–0.10). It is a mechanical prose detector, not a style preference.

`ASCII_ARROW_LINE_RE` exists solely to fail with a *specific* message ("use →
not ->") instead of a generic format complaint — a vague rejection makes agents
guess, and guessing is what produced repeated non-compliance.

## Read-only passthrough

A write-lock that also blocks reads makes the index un-auditable, which is how
orphaned files and dead pointers survive for months unnoticed.

A command is treated as read-only if it starts with
`cat|head|tail|wc|less|more|bat|grep|ls|stat|md5sum|diff|file|sort|uniq|awk|cut|tr`
**and** contains no `>` redirect, no live pipe, no `tee`, no `sed`, no `$(...)`,
and no backticks. All write vectors remain blocked.

**Known over-block:** requiring *zero* shell operators means a legitimate
read-only compound like `ls dir/ 2>&1; echo "---"; stat file` is classified as a
write, because of the `;` and the `2>&1`. Agents respond by splitting commands or
bypassing the shell entirely, which is friction rather than protection. Widening
the predicate to recognise read-only pipelines is the correct fix when you hit
it; add a regression case either way.

## Testing

```bash
# Read/write classification + path-argument cases
python3 scripts/test_hook_cases.py
```

Hooks register at **session start**. Editing the plugin does not change the
running session — verify with the scripts and a fresh session, never by
attempting a live call in the current one.

## Failure modes

**Hook blocks something that should pass.** Check the call against the read-only
predicate. If it's a legitimate read, widen the predicate and add a case to
`test_hook_cases.py`.

**Bypass found.** Any new write vector must be added to `_targets_memory_md`
**and** to the regression test. A vector that is blocked in code but untested
will regress silently.

**Unit tests pass but nothing is enforced.** The test script calls
`handle_pre_tool_call` directly, so it verifies the *logic* and not the
*wiring*. Confirm the hook is actually loaded with `hermes plugins doctor` and a
live refusal test.

**Plugin silently disabled.** Hook errors disable the gate for the session. Check
`hermes plugins list`; if it shows `not enabled`, run
`hermes plugins enable memory-shaper`.

**Manifest rejected.** `hermes plugins doctor <name>` reports the specific
problem: unknown hook names in `provides_hooks`, a manifest/registration
mismatch, or an unparseable YAML file (a trailing `---` is the usual cause).
`tool_execution` is middleware registered via `ctx` — it is not a valid
declarable hook.
