# Git Workflow

## Branching
- Short-lived branches, rebased on main before review. A branch older than a
  week is a merge conflict waiting to be discovered.
- Rebase local history, never shared history. If someone else has the commit,
  it gets a merge.

## Common operations
- `git worktree` for the "I need to check something on main without stashing"
  case. It is faster to reason about than a stash stack.
- `git stash` is a scratchpad, not storage. Anything that matters becomes a
  commit on a throwaway branch.

## Conflicts
- Resolve conflicts in the file, then run the tests — a clean merge is not
  evidence of a correct merge.
- When a cherry-pick conflicts, check whether the fix is already upstream
  before resolving by hand.

## How this file is routed to
Keywords: `git`, `branch`, `rebase`, `worktree`, `conflict`, `cherrypick`,
`stash`. This line and `deploy-pipeline.md` both concern shipping code, but
the keyword sets are disjoint — a question about a rebase conflict routes here
and not to the pipeline file, without either line needing to describe the
boundary in prose.
