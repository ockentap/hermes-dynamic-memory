# Stock-Hermes patch: flat memory entries (background, not an install step)

`0001-flat-memory-separator.patch` changes one file, `tools/memory_tool_store.py`, so the
memory store stops joining entries with the legacy `\n§\n` paragraph delimiter and keeps a
flat, newline-delimited index.

**This is not part of the catalog install and nothing in this repo asks you to apply it.**
A catalog plugin cannot modify Hermes, so the plugin does not depend on this patch: the
stock store is supported as-is (see "Why the plugin does not need it" below). The file is
kept because it documents the failure mode and because some users prefer the flat store.

## Why it exists

Stock Hermes treats entries as **paragraphs**: a file with no `§` parses as ONE entry (the
whole file), and the next write joins entries with `§`. For dynmem that means:

- the index header block (prose plus the template line) is a single entry, so a
  `remove`/`replace` matching anything inside it would delete every header line at once;
- the "one line per entry" format the plugin enforces is not what the store writes.

## Why the plugin does not need it

The plugin's guard closes the dangerous half from the hook side: any `remove` / `replace` /
`patch` whose `old_text` lands inside the header entry is refused unless the rewrite
sentinel is set, so the header cannot be wiped through the memory tool on a stock store.
The remaining difference is cosmetic — `§` separator lines appear between entries, and the
plugin treats them as separators rather than entries.

## What it changes

- Parsing: if the file has no `\n§\n`, each LINE is an entry; `§` files keep the paragraph model.
- Joining: the separator is learned per target from the file's bytes, and sticks after the
  store's own write, so a flat store stays flat and a `§` store keeps `§` (and its budget width).
- Budget arithmetic and the system-prompt block use the same learned separator.

## Applying it (optional, your choice)

```bash
cd /path/to/hermes-agent          # the install directory, not ~/.hermes
git apply -p1 /path/to/0001-flat-memory-separator.patch
hermes gateway restart            # a running gateway keeps the old module in memory
```

Re-apply after every `hermes update`. `git apply --check` first; it is base-version
sensitive. If you never apply it, everything in the plugin and the skills still works.
