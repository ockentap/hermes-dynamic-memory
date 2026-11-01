# The access watchdog

`scripts/dynmem-watchdog.py` keeps the index honest without a model in the loop.
It runs as a scheduled job, usually once a day.

## What it does
1. **Tally** — scans new tool calls in the session database for arguments that
   mention a topic filename, and records one access per message. Two counters are
   kept in the sidecar: `reads` (lifetime) and `days{}` (per-UTC-day buckets). The
   watermark lives in the same sidecar, so runs are incremental.
2. **Order** — sorts untagged index lines by reads inside the rolling window
   (default 30 days), then by last access. Lifetime reads are reported, not
   ranked: a file hammered during one project does not stay at the top for
   months. Tagged lines never move.
3. **Archive** — only when the index body passes about 95% of its character cap.
   It moves the least-accessed eligible entries to `archived memories/`, records
   their lines verbatim in `archived-memories.md`, and writes a timestamped backup
   of the index first.

## Protections
- `!!` and `!` entries are never reordered or archived.
- A grace window (default 14 days) protects new or recently touched files, so a
  new entry cannot be evicted merely for being unread.
- If the cap is exceeded but everything is protected, it warns instead of pruning.

## Restore
Move the file back out of `archived memories/`, re-add its recorded line, done.

## Flags
`--dry-run` reports without writing; `--report` prints a top/bottom access card.
Empty output on a scheduled run means "nothing to say".
