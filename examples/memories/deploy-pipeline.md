# Deploy Pipeline

## Shape
- Build once, promote the same artifact through staging and production. A
  rebuild between environments means you are not testing what you ship.
- Every deploy is reversible in one step. If rollback requires a forward fix,
  it isn't a rollback.

## Gates
- Canary at low traffic share, watch error rate and p95 latency, then widen.
  Time-based promotion is a proxy for confidence, not a measurement of it.
- Migrations run before the new code is serving, but must be compatible with
  the old code still running during the window.

## Standing notes
- Staging config drifts toward production over time and then diverges at the
  worst moment. Diff the two on a schedule.
- Secrets injected at runtime, never baked into images.

## How this file is routed to
The keywords are the operational vocabulary: `deploy`, `release`, `pipeline`,
`staging`, `rollback`, `canary`, `ci`. A conversation about a failing pipeline
and a conversation about a failing build share words like "broken" and "fail"
but almost nothing from this set — which is why the set, not the sentiment, is
what routes.
