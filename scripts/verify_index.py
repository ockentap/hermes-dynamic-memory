#!/usr/bin/env python3
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
# See the NOTICE file for attribution requirements.
"""Validate a candidate dynamic-memory index against a memories directory.

Checks (per line):
  - exactly one arrow (Unicode → recommended; ASCII -> tolerated on read)
  - target is a bare .md filename that EXISTS in the directory
  - no duplicate targets
  - keyword count within [MIN_KEYWORDS, MAX_KEYWORDS]
  - no duplicate keywords within a line
  - keywords lowercase, no spaces inside a keyword

Usage:
  python3 verify_index.py <candidate-index-file> [--memdir DIR]

The topic-file directory defaults to the candidate index file's own directory,
which is the normal layout (index and topic files side by side). Pass --memdir
explicitly to validate a candidate index against a directory elsewhere, e.g.
before writing it back to ~/.hermes/memories/.
Exit code 1 on any FAIL.
"""
import argparse
import glob
import os
import re
import sys

MIN_KEYWORDS, MAX_KEYWORDS = 5, 20
ARROWS = ("\u2192", "->")  # Unicode arrow first (house style), ASCII tolerated

# Hermes' built-in memory store joins entries with ENTRY_DELIMITER = "\n§\n"
# (tools/memory_tool_store.py), so a bare "§" line appears between entries in any
# file the memory tool has written more than once. The dynamic-memory format is
# NEWLINE-delimited — a newline means a new entry and no separator token is
# needed — so these lines are runtime artifacts, not entries. They are skipped
# rather than flagged: they are not content, and they carry no position.
SEPARATOR_CHARS = {"\u00a7", "\u2550", "="}


def is_separator_line(line: str) -> bool:
    """True for a bare separator/ruler line emitted by the memory store."""
    s = line.strip()
    if not s:
        return False
    if s in SEPARATOR_CHARS:
        return True
    return len(s) >= 3 and set(s) <= SEPARATOR_CHARS


# ─── Related edges (v1.7.0) ──────────────────────────────────────────────────
# A topic file may end with one "## Related" block holding at most five
# conditional links to sibling topic files:
#
#   ## Related
#   - when the user is cooking a specific dish → lasagna.md
#
# The condition is the whole point: the agent follows the edge only when it
# matches, so the cost is paid at read time, never in the always-injected index.
# The checks below keep that trail from rotting (missing targets, self links,
# run-away blocks) and flag the two shapes that cause ping-pong reads: direct
# back-links and cycles.
RELATED_HEADING_RE = re.compile(r"^#{2,3}\s*related(?:\s+(?:memories|edges))?\s*:?\s*$", re.IGNORECASE)
RELATED_EDGE_RE = re.compile(
    r"^[-*]\s+when\s+(?P<cond>\S.*?)\s+(?:\u2192|->)\s+(?P<target>[A-Za-z0-9_.\-]+\.md)\s*$",
    re.IGNORECASE,
)
MAX_RELATED_EDGES = 5
MIN_CONDITION_WORDS = 4


def related_blocks(text: str):
    """Yield (heading_line_number, [(line_number, line), ...]) for every *edge* block.

    A plain ``## Related`` list of links is ordinary prose and stays untouched —
    live topic files already carry sections like that. A block is treated as an
    edge block when the heading is the canonical ``## Related memories`` /
    ``## Related edges``, or when any bullet in it carries an arrow. That keeps
    the validator from failing files it never wrote while still rejecting a
    malformed edge in a block that is clearly trying to be one.
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        heading = lines[i].strip()
        if RELATED_HEADING_RE.match(heading):
            block, j = [], i + 1
            while j < len(lines) and not lines[j].lstrip().startswith("#"):
                block.append((j + 1, lines[j]))
                j += 1
            canonical = "memor" in heading.lower() or "edge" in heading.lower()
            has_arrow = any(
                ("\u2192" in l or "->" in l)
                for _, l in block if l.strip().startswith(("-", "*"))
            )
            if canonical or has_arrow:
                yield i + 1, block
            i = j
        else:
            i += 1


def check_related(memdir: str, onfile: set[str]):
    """Validate every ## Related block. Returns (edges_ok, failures, warnings, graph)."""
    ok, bad, warn = 0, [], []
    graph: dict[str, set[str]] = {}
    for path in sorted(glob.glob(os.path.join(memdir, "*.md"))):
        base = os.path.basename(path)
        if base.upper() in {"MEMORY.MD", "USER.MD", "ARCHIVED-MEMORIES.MD", "ARCHIVED-MEMORY.MD"}:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except Exception as exc:  # unreadable topic file
            bad.append((base, 0, f"UNREADABLE ({exc})"))
            continue
        for heading_lineno, block in related_blocks(text):
            edges = [(n, l.strip()) for n, l in block if l.strip().startswith(("-", "*"))]
            if len(edges) > MAX_RELATED_EDGES:
                bad.append((base, heading_lineno,
                            f"TOO MANY RELATED EDGES ({len(edges)} > {MAX_RELATED_EDGES})"))
            seen: set[str] = set()
            for lineno, line in edges:
                m = RELATED_EDGE_RE.match(line)
                if not m:
                    bad.append((base, lineno,
                                "RELATED LINE NOT AN EDGE (want: - when <condition> \u2192 file.md)"))
                    continue
                cond, target = m.group("cond").strip(), m.group("target")
                if len(cond.split()) < MIN_CONDITION_WORDS:
                    bad.append((base, lineno, f"RELATED CONDITION TOO VAGUE ('{cond}')"))
                if target == base:
                    bad.append((base, lineno, "RELATED SELF LINK"))
                    continue
                if target in seen:
                    bad.append((base, lineno, f"DUPLICATE RELATED TARGET '{target}'"))
                    continue
                if target not in onfile:
                    bad.append((base, lineno, f"RELATED TARGET MISSING '{target}'"))
                    continue
                seen.add(target)
                graph.setdefault(base, set()).add(target)
                ok += 1
    # Direct back-links and longer cycles: warnings, not build failures — a
    # deliberate two-way trail is allowed, it is just worth seeing.
    for src, targets in graph.items():
        for dst in sorted(targets):
            if src in graph.get(dst, set()):
                if src < dst:
                    warn.append((src, f"RECIPROCAL RELATED EDGE ({src} \u2194 {dst})"))
    def _walk(node, path, seen):
        for nxt in sorted(graph.get(node, ())):
            if nxt == path[0]:
                warn.append((path[0], "RELATED CYCLE " + " \u2192 ".join(path + [nxt])))
            elif nxt not in seen and len(path) < 6:
                _walk(nxt, path + [nxt], seen | {nxt})
    for start in sorted(graph):
        _walk(start, [start], {start})
    return ok, bad, warn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    ap.add_argument("--memdir", default=None,
                    help="directory holding the topic files "
                         "(default: the candidate index file's own directory)")
    args = ap.parse_args()

    with open(args.candidate, encoding="utf-8") as f:
        lines = f.read().splitlines()

    # The header block is prose plus the file list, terminated by the literal
    # template line; only lines after it are entries. Without that line the file
    # is validated line-by-line (the older comment-header style).
    header_refs: set[str] = set()
    _body_start = None
    for i, raw in enumerate(lines):
        if raw.strip().startswith("keyword,keyword,keyword"):
            _body_start = i
            header_refs = set(re.findall(r"([A-Za-z0-9_.\-]+\.md)\b",
                                         "\n".join(lines[:i])))
            lines = lines[i + 1:]
            break
    if _body_start is None:
        # Older comment-header style: '#' lines are the header, so a file named
        # there is still reachable and must not count as an orphan.
        header_refs = set(re.findall(r"([A-Za-z0-9_.\-]+\.md)\b",
                                     "\n".join(l for l in lines
                                               if l.strip().startswith("#"))))

    memdir = args.memdir or os.path.dirname(os.path.abspath(args.candidate)) or "."
    if not os.path.isdir(memdir):
        print(f"  [FAIL] memdir '{memdir}' is not a directory")
        return 1

    onfile = {os.path.basename(p) for p in glob.glob(os.path.join(memdir, "*.md"))}
    # Index-shaped files are self-describing and never count as orphans:
    # the live index, the user profile, and the archive index that lives
    # beside archived topic files (dynmem-watchdog.py writes it as
    # archived-memories.md; uppercase spellings accepted for safety).
    SELF_REFERRING = {"MEMORY.MD", "USER.MD", "ARCHIVED-MEMORIES.MD",
                      "ARCHIVED-MEMORY.MD"}
    onfile = {n for n in onfile if n.upper() not in SELF_REFERRING}

    ok, bad, seen_targets, separators = [], [], set(), 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if is_separator_line(line):
            # Runtime artifact from the memory store's entry join; not content.
            separators += 1
            continue
        arrow = next((a for a in ARROWS if a in line), None)
        if not arrow:
            bad.append(("NO ARROW", line))
            continue
        kw_part, target = line.rsplit(arrow, 1)
        kw_part, target = kw_part.strip(), target.strip()

        # Target checks
        if "/" in target or target.startswith("~"):
            bad.append(("TARGET NOT BARE", line))
            continue
        if target in seen_targets:
            bad.append(("DUPLICATE TARGET", line))
            continue
        if not target.endswith(".md"):
            bad.append(("TARGET NOT .MD", line))
            continue
        if target not in onfile:
            bad.append((f"ORPHAN (target '{target}' not in memdir)", line))
            continue
        seen_targets.add(target)

        # Keyword checks
        kws = [k.strip() for k in kw_part.split(",") if k.strip()]
        if not (MIN_KEYWORDS <= len(kws) <= MAX_KEYWORDS):
            bad.append((f"KEYWORD COUNT {len(kws)} outside [{MIN_KEYWORDS},{MAX_KEYWORDS}]", line))
            continue
        if len(kws) != len(set(kws)):
            bad.append(("DUPLICATE KEYWORDS", line))
            continue
        # Case is not a format error: kWh, VT, EPBiH and ModuleNotFoundError are
        # real routing keywords. Prose is what we reject, and prose means spaces.
        if any(" " in k or len(k) > 48 for k in kws):
            bad.append(("KEYWORD CONTAINS SPACE OR TOO LONG", line))
            continue
        ok.append(line)

    for line in ok:
        print(f"  [OK]   {line}")
    for reason, line in bad:
        print(f"  [FAIL] {reason}: {line}")

    # Reverse check: files on disk not referenced by any line. Files named in the
    # header block count as referenced — dynmem points its own docs at the header
    # instead of giving each one an index line.
    orphans = sorted(onfile - seen_targets - header_refs)
    for o in orphans:
        print(f"  [FAIL] ANTI-ORPHAN: file '{o}' exists on disk but has no index line")

    rel_ok, rel_bad, rel_warn = check_related(memdir, onfile)
    for base, lineno, reason in rel_bad:
        print(f"  [FAIL] {reason} ({base}:{lineno})")
    for base, reason in rel_warn:
        print(f"  [WARN] {reason} ({base})")

    total = len(ok) + len(bad) + len(orphans)
    note = f", {separators} separator line(s) ignored" if separators else ""
    print(f"\n{len(ok)} lines OK, {len(bad)} bad lines, {len(orphans)} orphaned files "
          f"({total} checks{note})")
    print(f"{rel_ok} related edges OK, {len(rel_bad)} related problems, "
          f"{len(rel_warn)} warnings")
    return 1 if (bad or orphans or rel_bad) else 0


if __name__ == "__main__":
    sys.exit(main())
