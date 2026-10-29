# Monthly consolidation

A scheduled pass that keeps the index from drifting, run as a scripted job with a
dry run first.

## What a pass checks
- **Duplicate targets** — two lines pointing at one file: merge the keywords.
- **Orphans** — files on disk with no line, and lines whose file is gone.
- **Prose** — any non-entry line below the template line.
- **Keyword bounds** — a line under 5 or over 20 keywords.
- **Stale pointers** — the topic changed enough that its keywords no longer
  describe it.

## Rules
- Never delete content to fix a count. Move detail into the topic file, or archive
  the whole topic.
- Back up the index before any rewrite, and report the diff.
- Cleanup that removes entries is a deliberate action: ask first, then do it in
  one reviewed batch.
- Prefer a plain script over an agent prompt — no tokens, no variance, and a diff
  you can read.
