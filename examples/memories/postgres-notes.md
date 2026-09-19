# Database Notes

## Query work
- `EXPLAIN ANALYZE` before and after every change; a query plan that looks
  reasonable on paper is routinely wrong about which step dominates.
- Indexes that are never used cost writes forever and pay nothing. Check
  `pg_stat_user_indexes` for zero-scan indexes each quarter.

## Migrations
- Every migration reversible, or explicitly marked as not. A migration that
  can only move forward gets reviewed twice.
- Add columns as nullable first, backfill in batches, then add the constraint.
  Single-statement schema changes on a large table are how maintenance windows
  get scheduled that nobody wanted.

## Maintenance
- Autovacuum handles the common case; the tables that need tuning are the
  high-churn ones with a low `autovacuum_vacuum_scale_factor`.
- Long-running transactions block vacuum from reclaiming anything, which shows
  up later as unexplained bloat.

## How this file is routed to
The keywords here are the ones a real debugging conversation contains —
`index`, `query`, `explain`, `migration`, `vacuum`. `index` is deliberately
listed without a qualifier: it appears in the index file's own vocabulary too,
and set-level scoring is what keeps a conversation about a database index from
being confused with a conversation about the memory index itself.
