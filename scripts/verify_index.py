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


def build_graph(memdir: str, onfile: set[str]) -> dict[str, set[str]]:
    """Parent -> children from every valid `## Related` edge block."""
    graph: dict[str, set[str]] = {}
    for path in sorted(glob.glob(os.path.join(memdir, "*.md"))):
        base = os.path.basename(path)
        if base.upper() in {"MEMORY.MD", "USER.MD", "ARCHIVED-MEMORIES.MD", "ARCHIVED-MEMORY.MD"}:
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except Exception:
            continue
        for _, block in related_blocks(text):
            for _, line in block:
                m = RELATED_EDGE_RE.match(line.strip())
                if not m:
                    continue
                target = m.group("target")
                if target != base and target in onfile:
                    graph.setdefault(base, set()).add(target)
    return graph


def index_depths(graph: dict[str, set[str]], roots: set[str]) -> dict[str, int]:
    """Node -> depth counted from the index line (indexed file = depth 1)."""
    depth: dict[str, int] = {r: 1 for r in roots}
    changed = True
    while changed:
        changed = False
        for src, targets in graph.items():
            if src in depth:
                d = depth[src] + 1
                for t in targets:
                    if t not in depth or d < depth[t]:
                        depth[t] = d
                        changed = True
    return depth


def check_tree(graph: dict[str, set[str]], roots: set[str], onfile: set[str],
               max_depth: int = 2):
    """Strict routing-tree rules, enabled by `--tree`.

    Depth is counted from the index line: the indexed file is depth 1, its
    children depth 2. A depth-2 tree is index -> hub -> leaf, which is the
    shape the measurements support (docs/routing-trees.md). Three rules are
    errors because each one makes routing ambiguous or defeats the point of
    the split:

      - TREE TOO DEEP: a node below max_depth (an extra summary line that
        must carry the child's words, which is where depth 3 lost accuracy);
      - DOUBLE-PARENT: one leaf reachable from two hubs, so two paths can
        disagree;
      - DOUBLE-HOMED: a file that is both indexed and a child, so the first
        hop can stop there and never see the tree.

    Returns (failures, warnings, stats).
    """
    bad, warn = [], []
    parents: dict[str, set[str]] = {}
    for src, targets in graph.items():
        for t in targets:
            parents.setdefault(t, set()).add(src)
    hubs = {n for n, ts in graph.items() if ts}
    leaves = {t for ts in graph.values() for t in ts} - hubs
    roots = {r for r in roots if r in onfile}
    depth = index_depths(graph, roots)
    for node, ps in sorted(parents.items()):
        if len(ps) > 1:
            if node in hubs:
                # Two paths into a synapse disagree about its whole subtree.
                bad.append((node, 0, "DOUBLE-PARENT (" + ", ".join(sorted(ps)) + ")"))
            else:
                # A shared engram is fine: several neurons may lead to the same
                # memory, and the keyword tables stay separate per parent.
                warn.append((node, "SHARED ENGRAM (" + ", ".join(sorted(ps)) + ")"))
    for node in sorted(roots & set(parents)):
        bad.append((node, 0, "DOUBLE-HOMED (index line + parent edge)"))
    for node, d in sorted(depth.items()):
        if d > max_depth:
            bad.append((node, 0, f"TREE TOO DEEP ({d} > {max_depth})"))
    for src in sorted(graph):
        if src not in depth and src not in parents:
            bad.append((src, 0, "HUB NOT REACHABLE FROM AN INDEX LINE"))
    stats = {
        "hubs": len([h for h in hubs if h in depth]),
        "leaves": len([l for l in leaves if l in depth]),
        "max_depth": max(depth.values(), default=0),
        "max_fanout": max((len(ts) for ts in graph.values()), default=0),
    }
    return bad, warn, stats


# ─── Keyword tiers (v1.9.0) ─────────────────────────────────────────────────
# Every neuron carries its own keyword line, with the same 5–20 band as the
# index:
#
#   keywords: alpha,beta,gamma,delta,epsilon
#
# Tiers: T1 = the index lines, T2 = the neurons they point at, T3 = the next
# hop, and so on — one more than `--tree` depth, which counts the indexed file
# as depth 1. Keywords are unique WITHIN a tier and may repeat ACROSS tiers, so
# a synapse may carry words from its own index line by design. The first five
# keywords on every line are the optimizer's locked block. Markers (!, !!, !!!)
# are index-only: they decide retention, and a neuron line has no retention
# policy of its own. Enforced only with `--keywords`, because a store that
# predates the rule has no headers yet.
KEYWORD_LINE_RE = re.compile(r"^keywords\s*:\s*(?P<list>\S.*)$", re.IGNORECASE)


def keyword_line(path: str) -> tuple[str, int, list[str]]:
    """Parse the first non-blank line of a neuron file.

    Returns (state, lineno, keywords): "ok", "missing" (no line at all),
    "misplaced" (a keyword line exists, but not first) or "empty".
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return "missing", 0, []
    first = next((i for i, l in enumerate(lines) if l.strip()), None)
    if first is None:
        return "empty", 0, []
    m = KEYWORD_LINE_RE.match(lines[first].strip())
    if m:
        return "ok", first + 1, [k.strip() for k in m.group("list").split(",") if k.strip()]
    for j in range(first + 1, min(first + 6, len(lines))):
        if KEYWORD_LINE_RE.match(lines[j].strip()):
            return "misplaced", j + 1, []
    return "missing", 0, []


def check_keyword_tiers(memdir: str, index_kw: dict[str, list[str]],
                        graph: dict[str, set[str]], roots: set[str],
                        onfile: set[str]):
    """Per-table keyword-line checks, enabled by `--keywords`.

    A keyword is unique inside one routing table, not across the whole store:
    the index is one table, and every neuron with links starts another for its
    children. So two files under different parents may use the same word, and a
    shared engram is checked against each parent's table separately.

    Returns (failures, collisions, stats).
    """
    bad: list[tuple[str, int, str]] = []
    depth = index_depths(graph, {r for r in roots if r in onfile})
    parents: dict[str, set[str]] = {}
    for src, targets in graph.items():
        for t in targets:
            parents.setdefault(t, set()).add(src)
    tables: dict[str, dict[str, set[str]]] = {}
    per_tier: dict[int, set[str]] = {}
    headers = 0

    for target, kws in index_kw.items():
        per_tier.setdefault(1, set()).add(target)
        for kw in kws:
            tables.setdefault("index", {}).setdefault(kw, set()).add(target)

    for base in sorted(depth):
        if base not in onfile:
            continue
        tier = depth[base] + 1
        state, lineno, kws = keyword_line(os.path.join(memdir, base))
        if state == "missing":
            bad.append((base, 0, f"NO KEYWORD LINE (tier {tier} wants "
                                 f"'keywords: ...' as the first line)"))
            continue
        if state == "misplaced":
            bad.append((base, lineno, "KEYWORD LINE NOT FIRST (move it above "
                                      "the heading)"))
            continue
        if state == "empty":
            bad.append((base, 0, "EMPTY FILE"))
            continue
        headers += 1
        if kws and kws[0].startswith("!"):
            bad.append((base, lineno, "MARKER IS INDEX-ONLY (a neuron line "
                                      "carries no !, !!, !!!)"))
            continue
        if not (MIN_KEYWORDS <= len(kws) <= MAX_KEYWORDS):
            bad.append((base, lineno, f"KEYWORD COUNT {len(kws)} outside "
                                      f"[{MIN_KEYWORDS},{MAX_KEYWORDS}] at tier {tier}"))
            continue
        if len(kws) != len(set(kws)):
            bad.append((base, lineno, "DUPLICATE KEYWORDS IN LINE"))
            continue
        if any(" " in k or len(k) > 48 for k in kws):
            bad.append((base, lineno, "KEYWORD CONTAINS SPACE OR TOO LONG"))
            continue
        per_tier.setdefault(tier, set()).add(base)
        for table in (parents.get(base) or {"index"}):
            for kw in kws:
                tables.setdefault(table, {}).setdefault(kw, set()).add(base)

    collisions: list[tuple[str, str, set[str]]] = []
    for table in sorted(tables):
        for kw, files in sorted(tables[table].items()):
            if len(files) > 1:
                collisions.append((table, kw, files))
    stats = {
        "tiers": max(per_tier, default=1),
        "headers": headers,
        "per_tier": {t: len(files) for t, files in per_tier.items()},
        "collisions": len(collisions),
    }
    return bad, collisions, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    ap.add_argument("--memdir", default=None,
                    help="directory holding the topic files "
                         "(default: the candidate index file's own directory)")
    ap.add_argument("--tree", action="store_true",
                    help="enforce routing-tree rules: max depth, one parent, "
                         "one entry point per file")
    ap.add_argument("--max-depth", type=int, default=2,
                    help="maximum tree depth counted from the index line "
                         "(default 2: index -> hub -> leaf)")
    ap.add_argument("--keywords", action="store_true",
                    help="enforce a keyword line in every routed neuron: 5-20 "
                         "keywords, unique within a tier, repeats across tiers ok")
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
    index_kw: dict[str, list[str]] = {}
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
        index_kw[target] = [k.strip() for k in kw_part.split(",") if k.strip()]

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

    # Related-edge validation runs BEFORE the orphan check: a child topic file
    # that is reachable through a `## Related` edge is not an orphan, even
    # without its own index line. That is the point of the trail — a detail file
    # hangs off its parent instead of costing a line in the always-injected index.
    rel_ok, rel_bad, rel_warn = check_related(memdir, onfile)
    related_targets = {
        target
        for path in glob.glob(os.path.join(memdir, "*.md"))
        for _, block in related_blocks(open(path, encoding="utf-8", errors="replace").read())
        for _, line in block
        if (m := RELATED_EDGE_RE.match(line.strip()))
        for target in [m.group("target")]
    }

    # Reverse check: files on disk not referenced by any line. Files named in the
    # header block count as referenced — dynmem points its own docs at the header
    # instead of giving each one an index line — and so does any Related target.
    orphans = sorted(onfile - seen_targets - header_refs - related_targets)
    for o in orphans:
        print(f"  [FAIL] ANTI-ORPHAN: file '{o}' exists on disk but has no index line")

    for base, lineno, reason in rel_bad:
        print(f"  [FAIL] {reason} ({base}:{lineno})")
    for base, reason in rel_warn:
        print(f"  [WARN] {reason} ({base})")

    # Routing-tree checks are opt-in (--tree): the same Related edges can be a
    # deliberate trail rather than a tree, and the default validator must not
    # fail those. In tree mode the shape becomes index line -> hub -> leaf.
    tree_bad: list = []
    tree_stats: dict = {}
    if args.tree:
        graph = build_graph(memdir, onfile)
        tree_bad, tree_warn, tree_stats = check_tree(graph, seen_targets, onfile,
                                                     args.max_depth)
        for base, lineno, reason in tree_bad:
            print(f"  [FAIL] {reason} ({base})")
        for base, reason in tree_warn:
            print(f"  [WARN] {reason} ({base})")
        print(f"tree: {tree_stats['hubs']} hubs, {tree_stats['leaves']} leaves, "
              f"depth {tree_stats['max_depth']}/{args.max_depth}, "
              f"max fan-out {tree_stats['max_fanout']}")

    # Keyword tiers are opt-in (--keywords): a store written before the rule has
    # no per-neuron keyword lines yet, so the default validator must not fail it.
    kw_bad: list = []
    kw_stats: dict = {}
    kw_collisions: list = []
    if args.keywords:
        graph = build_graph(memdir, onfile)
        kw_bad, kw_collisions, kw_stats = check_keyword_tiers(
            memdir, index_kw, graph, seen_targets, onfile)
        for base, lineno, reason in kw_bad:
            where = f" ({base}:{lineno})" if lineno else f" ({base})"
            print(f"  [FAIL] {reason}{where}")
        for table, kw, files in kw_collisions[:25]:
            shown = ", ".join(sorted(files)[:6]) + (" ..." if len(files) > 6 else "")
            where = "the index" if table == "index" else table
            print(f"  [FAIL] KEYWORD NOT UNIQUE UNDER {where}: '{kw}' → "
                  f"{len(files)} neurons ({shown})")
        if len(kw_collisions) > 25:
            print(f"  [FAIL] ... and {len(kw_collisions) - 25} more tier collisions")
        per_tier = ", ".join(f"T{t} {v}" for t, v in sorted(kw_stats["per_tier"].items()))
        print(f"keywords: {kw_stats['tiers']} tier(s) [{per_tier}], "
              f"{kw_stats['headers']} headers, {kw_stats['collisions']} collisions")

    total = len(ok) + len(bad) + len(orphans)
    note = f", {separators} separator line(s) ignored" if separators else ""
    print(f"\n{len(ok)} lines OK, {len(bad)} bad lines, {len(orphans)} orphaned files "
          f"({total} checks{note})")
    print(f"{rel_ok} related edges OK, {len(rel_bad)} related problems, "
          f"{len(rel_warn)} warnings")
    if args.tree:
        print(f"{len(tree_bad)} tree problems")
    if args.keywords:
        print(f"{len(kw_bad)} keyword-line problems, {len(kw_collisions)} tier collisions")
    return 1 if (bad or orphans or rel_bad or tree_bad or kw_bad or kw_collisions) else 0


if __name__ == "__main__":
    sys.exit(main())
