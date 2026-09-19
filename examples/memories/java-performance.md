# Java Performance

## Baseline
- G1 is the default collector here and has been fine up to ~4 GB heaps. Above
  that, pause times grow faster than throughput gains justify.
- Always measure with `-Xlog:gc*:file=gc.log` rather than guessing from
  application logs. GC pauses and application latency disagree more often
  than people expect.

## Recurring findings
- Most "memory leaks" in this codebase were unbounded caches, not object
  retention cycles. Look for a `Map` with no eviction policy first.
- Thread pools sized by default (`Executors.newFixedThreadPool`) are a frequent
  source of queue growth under load. Set the queue bound explicitly.

## Heap sizing
- Start at 2x live-set size, then trim. `-Xmx` should almost always equal
  `-Xms` on a dedicated host — resizing during steady state is pure overhead.
- Heap dumps: `jcmd <pid> GC.heap_dump`. Take two, an hour apart, before
  concluding anything is actually retained.

## How this file is routed to
This line owns the JVM vocabulary: `jvm`, `heap`, `garbagecollection`,
`profiling`, `jmx`. It deliberately does **not** own `scripting` or `runtime`
even though those words appear in prose here, because a file full of Java
detail otherwise wins conversations about unrelated scripting languages.

See `js-toolchain.md` for the other half of the naming collision — that line
carries `javascript`, `node`, and `bundler`, so a conversation about a broken
webpack build never has to compete with this file's keywords.
