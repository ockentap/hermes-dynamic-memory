# JavaScript Toolchain

## Build
- Vite for new projects; webpack only where a legacy config already exists and
  rewriting it isn't worth the risk.
- Build times above ~30 s are a signal, not a fact of life. Usually one plugin
  is doing far more work than it needs to.

## Dependencies
- `npm ci` in CI, never `npm install` — lockfile drift in CI produces failures
  that nobody can reproduce locally.
- Audit after adding a dependency, not on a schedule. A quarterly audit mostly
  produces noise about packages nothing imports.

## Linting and types
- Lint rules that fight the formatter get disabled, not argued with. Formatting
  is automated; correctness rules stay.
- `tsc --noEmit` in CI catches the type errors that a bundler happily strips.

## How this file is routed to
This line is the `javascript` half of a naming collision: it carries
`javascript`, `typescript`, `npm`, `bundler`, `webpack`, `vite`, `node`, and
`lint`, which are the words a real conversation about a broken frontend build
actually uses.

`java-performance.md` covers the JVM. The two domains collide on the bare
prefix `java`, and that is exactly the class of ambiguity set-level matching
resolves: a message mentioning "webpack" and "node_modules" scores this line
densely and the JVM line not at all, while "heap dump" and "GC pause" does the
reverse. A per-keyword scorer sees the shared substring and picks whichever
line it happened to walk first.
