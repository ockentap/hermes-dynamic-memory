---
name: dynmem-setup
description: "Use when installing dynmem on a stock Hermes instance."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [memory, dynmem, install, stock-hermes, patch, plugin, verification]
    related_skills: [dynamic-memory, hermes-agent, memory-integrity-checker]
---

# Installing dynmem on a regular Hermes

## When to Use

- Standing up dynmem on a Hermes that does not have it yet (fresh box, container,
  second profile).
- A dynmem install that is writing `§` paragraph separators, or whose header
  block disappeared after a memory edit.
- After `hermes update`, to re-verify that the hook still loads and the index
  still validates.

Not for: using dynmem day to day (that is the `dynamic-memory` skill), or
repairing an index — use the integrity checker for that.

Dynmem is a keyword index in the system prompt plus topic files on disk. Stock
Hermes does not behave that way out of the box: it joins memory entries with a
`\n§\n` paragraph delimiter, so the index header is ONE entry and a single
`remove` deletes it. The plugin fixes that from the hook side — it refuses an
edit whose `old_text` lands inside the header entry and ignores the `§` lines —
so no Hermes file is patched.

Do them in this order. Every step below was verified on stock v0.22.5.

## 0. Prerequisites

- Hermes ≥ 0.22.2 in any form (CLI install or Docker image).
- The dynmem repo checkout (`hermes-dynamic-memory`) — it holds the plugin, the
  skill, the scripts and the templates.
- Know `$HERMES_HOME` (not necessarily the install directory): `~/.hermes` for
  a normal install, `/opt/data` in the Docker image.

## 1. No core patch — the stock store is fine

Do not modify `tools/memory_tool_store.py`. On the stock store the header block
is a single `§`-joined entry; the plugin's guard refuses any `remove` / `replace`
/ `patch` whose `old_text` falls inside that entry, so the header cannot be
wiped through the memory tool, and the index reads fine with `§` lines present.
`scripts/patches/0001-flat-memory-separator.patch` is kept in the repo as
background only — it is not an install step.

If you do want the flat store (fewer separator lines, one entry per line in the
prompt view), apply that patch yourself and re-apply it after every update. The
plugin does not need it either way.

## 2. Install the plugin

```bash
mkdir -p $HERMES_HOME/plugins/memory-shaper
cp -r <repo>/plugin/memory-shaper/. $HERMES_HOME/plugins/memory-shaper/
hermes plugins enable memory-shaper
hermes plugins list | grep shaper      # expect: enabled + a version
```

With `docker cp`, create the destination directory first: copying a directory
onto an existing directory copies its CONTENTS, leaving `plugin.py` at
`plugins/` top level where discovery never finds it.

## 3. Install the skill and the scripts

```bash
cp -r <repo>/skill  $HERMES_HOME/skills/dynamic-memory
cp -r <repo>/scripts $HERMES_HOME/dynmem-scripts
```

`scripts/` gives you `verify_index.py`, `dynmem-watchdog.py` and the tests.
Every one takes a home argument or honours `HERMES_HOME`, so a container or a
second profile works without editing paths.

## 4. Seed the index

```bash
cp -r <repo>/examples/memories/.            $HERMES_HOME/memories/
cp    <repo>/examples/MEMORY.template.md    $HERMES_HOME/memories/MEMORY.md
cp    <repo>/examples/USER.template.md      $HERMES_HOME/memories/USER.md
```

Use `MEMORY.template.md` as the index, not `examples/memories/MEMORY.md` (that
one is the repo's demo). The template's placeholder note and example lines are
removed automatically by the plugin on the first real memory write; the
structural `keyword,keyword,keyword → file.md` line stays.

The template's `# All memories are located in: <MEMORIES_DIR>` line is replaced
by the plugin on the first load of the session with that profile's real absolute
path (idempotent; one backup at `$HERMES_HOME/state/memory-header-backup.md`).
If the line still says `<MEMORIES_DIR>` after a session has started, the plugin
is not loading — fix that before trusting retrieval.

## 5. Verify before trusting it

```bash
cd $HERMES_HOME/memories && python3 $HERMES_HOME/dynmem-scripts/verify_index.py MEMORY.md
python3 $HERMES_HOME/skills/memory-integrity-checker/scripts/check_memory.py   # if installed
python3 $HERMES_HOME/dynmem-scripts/dynmem-watchdog.py --home $HERMES_HOME --dry-run
```

Then the only test that matters — a write and a read in two sessions:

1. Ask the agent to save one durable fact (one topic file, one index line).
2. Check the file: header intact, one new entry, template placeholders gone.
   On an unpatched store a `§` line between entries is expected and harmless —
   it is the store's separator, not a broken index.
3. New session, ask for the fact from memory. It should answer and name the
   topic file it read.

## Pitfalls

- **A `§` line after a write is normal on a stock store.** It is the store's
  entry separator. The pass condition is the header plus one new entry; if you
  also want a flat file, that is the optional patch, not a requirement.
- **Do not patch Hermes to install this.** The plugin guards the header entry
  from the hook side, which is what stops a wipe; the store patch is background.
- **`docker cp` preserves ownership** (uid 1001, mode 0600). A service running as
  another user then cannot read the seeded files: `chown -R` them to the runtime
  user after copying.
- **Reading MEMORY.md through the shell** is always allowed, pipes and chains
  included (`grep … | head`). What the lock refuses is a write vector aimed at
  the index — a redirect to it, `| tee MEMORY.md`, `sort -o MEMORY.md`,
  `sed -i … MEMORY.md`, or a command substitution in a command that names it.
- **Protected lines**: removing or replacing the structural template line is
  refused without `MEMORY_SHAPER_ALLOW_REWRITE=1` or
  `$HERMES_HOME/state/.memory_shaper_rewrite_approved`.
- **Watchdog scheduling**: it is a plain script — run it from cron with
  `--home`, and it stays silent unless it archives something or the cap fires.
- **Updates**: after `hermes update`, re-run the write test and
  `scripts/test_hook_cases.py`; do not assume the hook still loads. If you did
  apply the optional store patch, `hermes update` replaced it — re-apply it or
  not, the plugin does not depend on it.
