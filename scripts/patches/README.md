# Stock-Hermes patch: flat memory entries

`0001-flat-memory-separator.patch` changes one file, `tools/memory_tool_store.py`, so the
memory store stops joining entries with the legacy `\n§\n` paragraph delimiter and keeps a
flat, newline-delimited index.

## Why it is needed

Stock Hermes treats entries as **paragraphs**: a file with no `§` parses as ONE entry (the
whole file), and the next write joins entries with `§`. For dynmem that means:

- the index header block (prose plus the template line) is a single entry, so a
  `remove`/`replace` matching anything inside it deletes every header line at once;
- the "one line per entry" format the plugin enforces is not what the store writes.

## What it changes

- Parsing: if the file has no `\n§\n`, each LINE is an entry; `§` files keep the paragraph model.
- Joining: the separator is learned per target from the file's bytes, and sticks after the
  store's own write, so a flat store stays flat and a `§` store keeps `§` (and its budget width).
- Budget arithmetic and the system-prompt block use the same learned separator.

## Applying it

```bash
cd /path/to/hermes-agent          # the install directory, not ~/.hermes
git apply -p1 /path/to/0001-flat-memory-separator.patch
hermes gateway restart            # a running gateway keeps the old module in memory
```

Re-apply after every `hermes update`. `git apply --check` first; it is base-version
sensitive.
