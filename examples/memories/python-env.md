# Python Environment

## Project setup
- One virtualenv per project, committed `pyproject.toml`, hashed lockfile.
- Never install into the system interpreter. The failure mode is silent: a
  script works locally and fails in CI for reasons that take an hour to find.

## Tooling
- `ruff` for linting and formatting in one pass; fewer tools in the loop means
  fewer disagreements between them.
- `pytest` with `-x` while iterating, full suite in CI. Fixing the first
  failure often makes the next three disappear.
- Type-check the boundaries — anything crossing a module or IO edge — rather
  than annotating every internal helper. Full coverage has a cost, and the
  cost lands on every future edit.

## How this file is routed to
Keywords cover `python`, `venv`, `packaging`, `poetry`, `ruff`, `pytest`,
`typing`. Note that `java-performance.md` also discusses tooling, but the two
lines share no meaningful keyword intersection, so a question about virtualenv
recursion never pulls in a JVM file. Overlap in *topic* is fine; overlap in
*keywords* is what causes misroutes.
