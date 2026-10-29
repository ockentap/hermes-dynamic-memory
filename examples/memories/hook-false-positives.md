# Hook false positives

The write lock exists to stop anything but the memory tool from mutating the
index. It is conservative, so it also blocks innocent commands.

## What gets blocked
- Compound shell commands that mention the index path, even when the first word
  is read-only: `cat <index> && echo done` is refused; plain `cat <index>` is not.
- Scripts whose source contains an obvious write to the index, even if that branch
  never runs.
- `sed -i`, `tee`, and any redirect targeting the index — always, by design.

## Workarounds
- Read with a single plain command (`cat`, `head`, `wc`, `grep`) and no pipe, no
  `tee`, no `sed`, no command substitution.
- For content, prefer the memory tool over the shell.
- A deliberate wholesale rebuild needs the documented escape hatch: set the
  rewrite-approval environment variable, or create the approval file, then retry.
  It is logged.
