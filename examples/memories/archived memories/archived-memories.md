# Archived Memories — archived-memories.md
#
# Keyword index for memory topic files pruned from the live memories/MEMORY.md
# index. Archiving is eviction from the HOT index, NOT deletion: every file
# here is complete and readable, and each line below is the exact index entry
# that was removed from MEMORY.md. Search this file the same way you search the
# live index — it is a normal keyword table, one step above any deep archive in
# the retrieval order.
#
# Rules the archiver (scripts/dynmem-watchdog.py) enforces: pinned (!) and
# critical (!!) entries are never archived, and files younger than 14 days are
# never archived.
#
# Index backups taken before each prune run live in this directory as
# `MEMORY.md.bak-<timestamp>`. To restore an entry: move `NAME.md` back into
# `memories/` and re-add its line via the memory tool — the line below is
# verbatim what to re-add. Eviction stats (reads, dates) live in the sidecar
# `.access-tally.json`, not in the lines here.
#
## Archive index

database,postgres,index,query,explain,migration,vacuum → postgres-notes.md
