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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    ap.add_argument("--memdir", default=None,
                    help="directory holding the topic files "
                         "(default: the candidate index file's own directory)")
    args = ap.parse_args()

    with open(args.candidate, encoding="utf-8") as f:
        lines = f.read().splitlines()

    memdir = args.memdir or os.path.dirname(os.path.abspath(args.candidate)) or "."
    if not os.path.isdir(memdir):
        print(f"  [FAIL] memdir '{memdir}' is not a directory")
        return 1

    onfile = {os.path.basename(p) for p in glob.glob(os.path.join(memdir, "*.md"))}
    onfile.discard("MEMORY.md")
    onfile.discard("USER.md")

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
        if any(k != k.lower() or " " in k for k in kws):
            bad.append(("KEYWORD NOT LOWERCASE/CONTAINS SPACE", line))
            continue
        ok.append(line)

    for line in ok:
        print(f"  [OK]   {line}")
    for reason, line in bad:
        print(f"  [FAIL] {reason}: {line}")

    # Reverse check: files on disk not referenced by any line
    orphans = sorted(onfile - seen_targets)
    for o in orphans:
        print(f"  [FAIL] ANTI-ORPHAN: file '{o}' exists on disk but has no index line")

    total = len(ok) + len(bad) + len(orphans)
    note = f", {separators} separator line(s) ignored" if separators else ""
    print(f"\n{len(ok)} lines OK, {len(bad)} bad lines, {len(orphans)} orphaned files "
          f"({total} checks{note})")
    return 1 if (bad or orphans) else 0


if __name__ == "__main__":
    sys.exit(main())
