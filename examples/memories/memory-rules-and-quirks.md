# How the memory tool actually behaves

## Actions
- `add` — appends one entry. Exact duplicates are refused.
- `replace` — replaces the WHOLE matched entry. `old_text` only locates it; the
  matched span is not spliced into the new text.
- `remove` — deletes the matched entry. The substring must match exactly one entry.
- Batches are all-or-nothing and are budget-checked against the final state.

## Quirks worth knowing
- Entries are parsed one per line. A section-sign character anywhere in the file
  can flip the parser into a paragraph model, after which entry-level writes are
  refused as "content that wouldn't round-trip". Keep it out of the file entirely.
- The tool rewrites the whole file from parsed entries, so leading indentation and
  blank lines are dropped on the next write. Do not rely on them.
- The in-prompt copy is a frozen snapshot taken at session start. A write is
  visible to the next session, not the current one.
- Content is scanned before it is accepted: prompt-injection and
  credential-exfiltration shapes are refused, not stored.
- If a write is refused for capacity, retry as one batch that removes or shortens
  stale entries AND adds the new one — the limit is checked on the final result
  only.
