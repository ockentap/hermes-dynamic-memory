# Memory retrieval order

Stop at the first step that answers the question.

1. **Keywords.** The index is already in the prompt. A keyword match → read that
   topic file. Free, no tool call.
2. **Grep the live files.** Take the nouns, tool names and symptom words out of
   the user's message and grep the topic-file contents, ranked by hit count:

```bash
cd ~/.hermes/memories && grep -ric "<noun>" --exclude=memory-retrieval-order.md \
  *.md | grep -v ':0$' | sort -t: -k2 -rn | head -10
```

3. **Archive index.** `archived memories/archived-memories.md` — same shape.
   Pruned is not deleted; read the archived file like any other.
4. **Grep the archived files.** Same command, `archived memories/*.md`.
5. **Installed MCP memory helper**, if the user has one.
6. **Old conversations** — full-text search over session history.
7. **Skills and plugins** — the procedure usually lives there.
8. **Further out** — web, docs, or direct filesystem recon.

## Limits
Grep is literal: a file that only says "bootloader" is invisible to a grep for
"firmware". Steps 2 and 4 need the store to be plain text on disk — the property
a vector or cloud store does not have.
