# Dynamic memory — format reference

## The line

```
keyword,keyword,keyword → file.md
```

| Part | Rule | Rejected example |
|---|---|---|
| keywords | 5–20, lowercase, comma-separated, no spaces inside a keyword | `Memory, Index, Tool` |
| arrow | Unicode `→` (U+2192), single space either side | `->` |
| target | bare `*.md` filename in the same directory | `memories/foo.md`, `~/foo.md`, `/abs/foo.md` |
| count | exactly one line per topic file | two lines → same file |
| content | keywords only — no prose, no parentheticals (a bare `§` line is a runtime separator, not content — see below) | `Notes about the memory tool (see docs)` |

## Header vs body

Prose is permitted only in the header, and the header/body boundary is the
template line (`keyword,keyword,keyword → file.md`). Everything above it is
header; everything below it must be an index line.

## Qualifier prefixes

```
!!  critical — do not modify without explicit user approval
!   pinned   — never prune; content may still be updated
    (none)   — normal; may be reordered and pruned
```

User-assigned only. Agents may propose with reasons; the user decides.

## Violation gallery

Real violations, with the reason each one fails.

**Prose in the index**
```
The user prefers concise responses and dislikes walls of text → user-preferences.md
```
Comma/word ratio far below 0.5. This is the most common failure — the fix is to
write the sentence into the topic file and reduce the line to keywords.

**Wrong arrow**
```
memory,tool,format,index -> how-to-write-memories.md
```
ASCII `->` is rejected at two independent points, with a specific message. If a
tool objects to `→`, the tool is wrong.

**Path in the target**
```
memory,tool,format,index,keyword → ~/.hermes/memories/how-to-write-memories.md
```
Targets are bare filenames. The directory is implied by the index location.

**Too few keywords**
```
memory,tool → how-to-write-memories.md
```
Below the floor of 5 — under-specified, and unlikely to match how anyone asks.

**Padded keywords**
```
memory,tool,use,make,file,work,data,info,url → how-to-write-memories.md
```
Above 5, but the padding is generic filler that matches nearly every query.
Generic words are false positives, not coverage. A short line is better than a
padded one.

**Duplicate target**
```
memory,tool,format,index,keyword → how-to-write-memories.md
memory,write,entry,template,verbose → how-to-write-memories.md
```
One line per topic file. Note: the hook does **not** catch this — only the
validator does. Two lines pointing at one file means the keyword sets compete
and neither is authoritative.

**Bare line, no arrow**
```
memory,tool,format,index,keyword
```
Not a pointer. Unreachable content plus index noise.

**Comment inside the body**
```
# Routing notes
memory,tool,format,index,keyword → how-to-write-memories.md
```
The header may carry comments; the body may not. A `#` line below the template
line is either header content in the wrong place or a stray artifact.

**Orphaned topic file** (no line references it)
```
memory-retrieval-order.md exists in ~/.hermes/memories/, but no index line points to it
```
Unreachable content. It is invisible to the agent forever, and the file's mere
existence makes the index look complete.

**Dead target** (line points at a missing file)
```
old,topic,keywords,here,now → deleted-file.md
```
The agent reads the line, tries the file, gets an error, and burns a turn. Worse
than no line, because the line actively asserts content exists.

**Separator lines (`§`)**

Hermes' memory store joins entries with `"\n§\n"` (`tools/memory_tool_store.py`),
so a bare `§` line appears between entries in any file the `memory` tool has
written more than once. The format is newline-delimited, so these lines carry no
meaning — but they are unavoidable runtime artifacts.

`verify_index.py` **skips** them and reports the count. It does not flag them,
and it should not: flagging an artifact the runtime inserts unconditionally just
trains the reader to ignore validator output.

```
2 lines OK, 0 bad lines, 0 orphaned files (4 checks, 1 separator line(s) ignored)
```

The difference from a violating `§`: a **bare** `§` line (or a `═`/`=` ruler) is a
separator and is ignored; a `§` *inside* an index line's content is still wrong,
because it means prose or a paragraph model crept into the line.

## The prose detector

The plugin computes `commas / whitespace-separated-words` and rejects anything
below 0.5.

| Content | Ratio |
|---|---|
| A clean index line | ≥ 2.0 |
| A short prose sentence | 0.01–0.10 |
| **Threshold** | **0.5** |

It is a mechanical detector, not a style rule. If you find yourself trying to
phrase a sentence so it passes the ratio check, stop — write it to a topic file
and add a pointer.
