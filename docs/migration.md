# Migrating a flat store to neurons

Status: design, 2026-11-10. Not implemented yet.

A store written under the 1.5–1.8 line is flat: every line in `MEMORY.md` points
straight at a content file. That is a valid dynmem store — nothing breaks — but it
is the request-cheap shape: every memory is resident as a line, and the index
grows linearly with the store. The token-cheap shape needs **synapses**: one line
per domain, holding route lines to its children.

The migration is **agent-guided**. A script cannot tell that `aklima-android-app`
and `energy-prices-bih` belong to one domain while `vaultwarden` does not; the
agent reads the store and proposes the grouping, the script executes the
mechanics and proves nothing was lost.

## Safety model — redundancy before anything irreversible

Nothing is deleted, ever. The only irreversible act is rewriting `MEMORY.md`, and
that is the last step, gated on a content check.

| Layer | What | Where |
|---|---|---|
| A | full copy of the store before the run | `$HERMES_HOME/memories-backup/<run-id>/` |
| B | second copy off the store tree (different path, same disk) | `~/dynmem-migrations/<run-id>/store.tar.gz` |
| C | per-file `.orig` copies of every file the run rewrites | `<A>/files/` |
| D | the plan itself, frozen before execution | `<B>/plan.json` |
| E | manifest: sha256 of every original file, every line move (old index line → new synapse line), every created file and its sources | `<B>/manifest.json` |
| F | rollback: `migrate --undo <run-id>` restores A, verifies, and refuses if the store changed since the run | — |

Content-preservation gate: before `MEMORY.md` is rewritten, every non-route line
of every original file must appear **byte-identical** somewhere in the new store
(a multiset hash over all body lines). If one line is missing, the run aborts with
the index untouched. Moving text is the only allowed transformation; losing or
rewriting it is a bug.

## Procedure

1. **Read** — index plus every file it points at; note which files are pure
   content and which already route.
2. **Plan** — the agent writes `plan.json`: domains (name, 5–20 keywords for the
   new index line, children, one-line rationale), and for each child the
   keywords that move onto its parent's route line.
3. **Check** — `migrate --check-plan plan.json` validates mechanically: every
   index line accounted for exactly once, every target exists, keyword counts in
   band, no duplicate keyword within a table, no domain with a single child.
4. **Show** — the user sees: domains, child counts, index lines before → after,
   and the backup paths. Explicit yes required; the default is dry-run.
5. **Apply** — `migrate --apply plan.json` takes backups A–D, creates the synapse
   files, moves the keyword lines, rewrites the index, writes the manifest, then
   runs the content gate.
6. **Verify** — `verify_index.py --tree --keywords`, the hook-case battery, and a
   read of three random engrams through the new route. The run is only reported
   as done when all three pass.
7. **Undo** — `migrate --undo <run-id>` for the rest of the week; backups stay 30
   days.

## Scope

- **Single level first**: `index → synapse → engram`. A domain that needs a second
  level is split later with `deepen.py`, per file, with the same backup rules.
- A domain of one child is refused (a synapse with one route is a wasted hop);
  that line stays flat in the index.
- Engrams are untouched: no rewriting, no keyword stripping — their keywords are
  copied, never moved out of the file they describe.

## What the agent must not do

- No migration while another process is writing the store (the watchdog, an
  optimizer tick, a cron). Take the store lock or wait.
- No "tidy up while we're here": the plan is the whole diff. Anything else is a
  second run.
- No partial apply. Either the plan validates and the gate passes, or the store is
  restored and the run is reported as failed.
