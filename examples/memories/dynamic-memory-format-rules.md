# Format rules for the index

## Two tiers
- The index file — one `keyword,keyword → file.md` line per topic file.
- `<topic>.md` — free-form markdown, read only when a line routes to it.

## Line format
```
keyword,keyword,keyword → file.md
```
- Bare filename in the same directory; no paths, no absolute targets.
- One line per topic file; no duplicate targets.
- Keywords lowercase, comma-separated, 5–20 per line.
- No prose, no sentences, no parentheticals, no explanations.

## Arrow and delimiter
- Unicode `→` with one space on each side. Do not normalize it to `->` to satisfy
  a validator; fix the validator instead.
- The file is newline-delimited. One entry per line, no section-sign markers, no
  blank-line paragraphs, no prose entries.
- Why so strict: entries are parsed one line at a time. A paragraph or
  section-sign form makes the whole file a single entry, so an entry-level edit
  cannot be applied safely.

## Header
A header block of prose is allowed above the entries and ends at the literal
template line `keyword,keyword,keyword → file.md`. Everything after that line is
an entry. Anything that is not an entry after that line is a format error.
