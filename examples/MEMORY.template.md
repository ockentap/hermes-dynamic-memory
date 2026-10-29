# Dynamic Memory Index — dynmem
A keyword routing table, not the knowledge base: keywords map to a topic file here; read that file on a match.
Absence from this index is not absence of knowledge.
Search order: 1) match keywords 2) grep the live files 3) archived index (archived memories/archived-memories.md) 4) grep the archive 5) MCP helper 6) old conversations 7) skills and plugins 8) further out.
Say what you searched before saying you don't have it.
If the user installs an MCP memory server, add it by name to 5.
Markers: !! never edit or move without asking · ! never prune · none normal.
Working on this index itself — these files are reached from here, not from their own entries:
how-to-write-memories.md — what to save and skip, entry shape, keyword bounds, cap handling. Read before creating a memory.
dynamic-memory-format-rules.md — arrow, delimiter, keyword and plugin rules. Read before editing an entry or this header.
memory-rules-and-quirks.md — how the memory tool behaves: replace, patch, remove, denylist, pruning, quirks. Read when a write is refused.
hook-false-positives.md — plugin hook blocks that hit innocent commands, and their workarounds.
memory-retrieval-order.md — the search order and the file-grep command. Read when a search goes past this index.
dynmem-watchdog.md — daily tally, eviction, archive, restore. Read before touching the archive.
memory-consolidation-cron.md — the monthly index-clean job. Read before the monthly consolidation.
memory-benchmark-methodology.md — how the memory benchmark is run and scored.
TEMPLATE — the 7 example lines below are placeholders for the reader: the plugin deletes them, and this note, as soon as the first real memory is written. The line above them is structural and must not be deleted or edited.
keyword,keyword,keyword → file.md
python,venv,packaging,poetry,ruff,pytest,typing,imports → python-env.md
javascript,typescript,npm,bundler,webpack,vite,node,lint → js-toolchain.md
java,springframework,jvm,garbagecollection,heap,profiling,jmx → java-performance.md
deploy,release,pipeline,staging,rollback,canary,ci → deploy-pipeline.md
laptop,hardware,ram,ssd,thermal,battery,upgrade → laptop-hardware.md
network,router,wifi,dns,subnet,vpn,firewall → home-network.md
git,branch,rebase,merge,conflict,cherrypick,worktree,hook → git-workflow.md
