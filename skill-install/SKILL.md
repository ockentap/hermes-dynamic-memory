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
- After `hermes update`, to re-apply the flat-separator patch and re-verify.

Not for: using dynmem day to day (that is the `dynamic-memory` skill), or
repairing an index — use the integrity checker for that.

Dynmem is a keyword index in the system prompt plus topic files on disk. Stock
Hermes does not behave that way out of the box: it joins memory entries with a
`\n§\n` paragraph delimiter, so the index header is ONE entry and a single
`remove` deletes it. Two pieces fix that — a small core patch and the plugin.

Do them in this order. Every step below was verified on stock v0.22.5.

## 0. Prerequisites

- Hermes ≥ 0.22.2 in any form (CLI install or Docker image).
- The dynmem repo checkout (`hermes-dynamic-memory`) — it holds the patch, the
  plugin, the skill, the scripts and the templates.
- Know the install directory (not `~/.hermes`): e.g. `/opt/hermes` in the Docker
  image, `~/.hermes/hermes-agent` for a git install.

## 1. Apply the flat-separator patch

```bash
cd <install-dir>                      # /opt/hermes for Docker
patch -p1 --dry-run -i <repo>/scripts/patches/0001-flat-memory-separator.patch
git apply -p1 <repo>/scripts/patches/0001-flat-memory-separator.patch
```

What it changes in `tools/memory_tool_store.py`: parse one entry per LINE when
the file has no `§`; learn the join separator from the file's bytes and keep it
sticky; use it for budgets and the prompt block.

**Restart the process afterwards.** A running gateway keeps the old module in
memory — before the restart writes still emit `§`. In the Docker image the
gateway is an s6 service: `hermes gateway restart`.

Re-apply after every `hermes update`. If the base version moved, use
`git apply --check` first and fix the hunks rather than forcing them.

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

## 5. Verify before trusting it

```bash
cd $HERMES_HOME/memories && python3 $HERMES_HOME/dynmem-scripts/verify_index.py MEMORY.md
python3 $HERMES_HOME/skills/memory-integrity-checker/scripts/check_memory.py   # if installed
python3 $HERMES_HOME/dynmem-scripts/dynmem-watchdog.py --home $HERMES_HOME --dry-run
```

Then the only test that matters — a write and a read in two sessions:

1. Ask the agent to save one durable fact (one topic file, one index line).
2. Check the file: **no `§` lines**, header intact, one new entry, template
   placeholders gone.
3. New session, ask for the fact from memory. It should answer and name the
   topic file it read.

## Pitfalls

- **No `§` in the output after a write** is the pass condition. If `§` appears,
  the patch is not in the running process — restart the gateway, then retest.
- **Do not skip the patch** and hope the plugin covers it. The plugin guards, the
  store writes; on a `§` store the whole header block is one entry.
- **`docker cp` preserves ownership** (uid 1001, mode 0600). A service running as
  another user then cannot read the seeded files: `chown -R` them to the runtime
  user after copying.
- **Reading MEMORY.md through the shell** is allowed only as a simple read
  command. Compound commands (`cat X; echo y`) or pipes get refused by the
  plugin's lock, which looks like a broken file but is the guard working.
- **Protected lines**: removing or replacing the structural template line is
  refused without `MEMORY_SHAPER_ALLOW_REWRITE=1` or
  `$HERMES_HOME/state/.memory_shaper_rewrite_approved`.
- **Watchdog scheduling**: it is a plain script — run it from cron with
  `--home`, and it stays silent unless it archives something or the cap fires.
- **Updates**: `hermes update` replaces the patched file. Re-apply, restart, and
  re-run the write test; do not assume the format survived.
