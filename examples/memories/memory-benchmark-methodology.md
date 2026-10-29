# Benchmark methodology

The question is not "how many facts survive" but "do structured, detailed
memories survive" — a policy with its exceptions, a deploy order with its gates.

## Setup
- Rebuild clean containers from keeper images; wipe sessions and any existing
  memory state, and verify zero messages before installing fixtures.
- Install fixtures by direct file write, never by asking an agent to save them.
- One fresh session per question, so memory is the only possible source.
- Pass credentials at runtime; bake nothing into the image.

## Arms
- **Native** — the built-in store at its default cap.
- **Index** — the same facts behind a keyword index and topic files.
- Both arms get the same fixtures, the same probes, and the same model.

## Scoring
- **Mechanical** — exact strings and numbers, matched programmatically.
- **Adjudicated** — an independent judge scores detail coverage where wording
  varies, with the rubric written before the run.
- Report both, plus variance across runs. A single run is an anecdote.

## Hygiene
Delete containers under disk pressure, keep the results files, and record the
model, version and cap alongside every result — a benchmark without its
conditions is marketing.
