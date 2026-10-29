# How to write memories

## What belongs in the index
A durable fact that will still matter in a month: a decision and why, a
convention, a working command, a failure mode you paid for. If it is only useful
today, it does not belong here.

## What does not
- Anything the filesystem, `--help`, or a web search already answers.
- Raw dumps: logs, code blocks, tables.
- Ephemeral state: temporary paths, one-off debugging context.
- Procedures with steps — those are skills, which load on demand and do not
  compete for the prompt budget.

## Writing an entry
1. Write the detail into a topic file in this directory first.
2. Add one line to the index: `keyword,keyword,keyword → topic.md`.
3. 5–20 keywords, lowercase, no spaces inside a keyword.
4. Use the words the user actually types, including symptom words ("broken",
   "won't start") — those route better than internal jargon.
5. One line per topic file; never two lines pointing at the same file.

## When the cap is reached
Consolidate before adding: merge two overlapping entries into one, or move detail
into the topic file and shorten the line. If a whole topic has gone cold, archive
it — move the file and its line to `archived memories/` rather than deleting.
