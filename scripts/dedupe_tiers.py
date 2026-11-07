#!/usr/bin/env python3
"""Resolve tier-1 keyword collisions in a dynamic-memory index.

One keyword, one owner at T1. For every keyword that appears on two or more
index lines, pick the line most likely to own it and drop it from the others:

  filename token match  >  position 0  >  frequency in the file body

A line never goes below the five-keyword floor: when a removal would, the line
first gets a replacement from its own file, and only structural identifiers
qualify (paths, snake_case, dotted names, IPs) — never prose, never a word that
another line already owns. The rewritten index is validated before it is kept.

Dry-run by default. `--apply` writes the store after taking a timestamped copy
of MEMORY.md; `--shadow DIR` works on a copy of the store instead.
"""
from __future__ import annotations

import argparse
import collections
import os
import pathlib
import re
import shutil
import time

MIN_KEYWORDS, MAX_KEYWORDS = 5, 20

ARROW = "\u2192"
HEADER_STOP = "keyword,keyword,keyword"
MARKER_RE = re.compile(r"^(?P<marker>!{1,3})(?P<kw>\S+)$")

# Structural candidates only: a path, a snake_case id, a dotted name, an IP, or
# a version. Prose words are never promoted into the index by a script.
CANDIDATE_RES = [
    re.compile(r"\b(?:[\w.-]+/){2,6}[\w.-]+\b"),          # deep paths
    re.compile(r"\b[a-z0-9_]+/[a-z0-9_]+\b"),             # single-slash ids
    re.compile(r"\b[a-z0-9]+(?:_[a-z0-9]+)+\b"),           # snake_case
    re.compile(r"\b[a-z][a-z0-9]+(?:-[a-z0-9]+)+\b"),      # hyphenated ids
    re.compile(r"\b[a-z][a-z0-9]*(?:\.[a-z0-9]+){2,}\b"),  # dotted names
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),            # IPs
    re.compile(r"\b[a-z][a-z0-9]*\.(?:py|sh|js|ts|json|yaml|yml|md|conf|service|timer|log)\b"),
]

# A generic word that also names a sub-topic file (cron-dryrun-approval.md) is
# still owned by the general topic; these calls were made by hand once and are
# kept so a re-run reproduces them instead of re-litigating.
OVERRIDES = {
    "cron": "automation-workflows.md",
    "pi": "pi-hermes.md",
    "hermes": "hermes-agent-config.md",
    "vps": "oracle-vps-migration.md",
    "oracle": "oracle-vps-migration.md",
    "auth.json": "api-key-search-before-ask.md",
    "optiplex": "dietpi-optiplex7050.md",
    "bosnian": "alminasv-profile.md",
    "plugin": "authorization-plugins.md",
}
GENERIC = {
    "this", "that", "with", "from", "have", "will", "when", "then", "than", "they",
    "their", "which", "while", "what", "were", "your", "should", "could", "would",
    "about", "after", "before", "because", "other", "into", "file", "files", "line",
    "lines", "note", "notes", "true", "false", "none", "work", "works", "working",
    "used", "using", "make", "made", "need", "needs", "same", "only", "also", "very",
    "much", "more", "most", "some", "such", "here", "does", "done", "each", "both",
    "must", "over", "under", "again", "check", "checked", "value", "values", "thing",
    "things", "case", "cases", "memory", "memories", "index", "keyword", "keywords",
}


def parse_entry(line: str) -> dict | None:
    """`[marker]kw,kw → file.md` -> dict, or None when the line is not an entry."""
    raw = line.rstrip("\n")
    if ARROW not in raw or raw.strip().startswith("#"):
        return None
    kw_part, target = raw.rsplit(ARROW, 1)
    target = target.strip()
    if not target.endswith(".md") or "/" in target:
        return None
    kws = [k.strip() for k in kw_part.split(",") if k.strip()]
    if not kws:
        return None
    marker = ""
    m = MARKER_RE.match(kws[0])
    if m:
        marker, kws[0] = m.group("marker"), m.group("kw")
    return {"marker": marker, "kws": kws, "target": target, "raw": raw}


def render(entry: dict) -> str:
    kws = list(entry["kws"])
    if entry["marker"]:
        kws[0] = entry["marker"] + kws[0]
    return ",".join(kws) + " " + ARROW + " " + entry["target"]


def read_store(store: pathlib.Path):
    lines = (store / "MEMORY.md").read_text(encoding="utf-8").splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith(HEADER_STOP):
            start = i + 1
            break
    entries, head = [], lines[:start]
    for line in lines[start:]:
        e = parse_entry(line)
        if e:
            entries.append(e)
    return head, entries, lines[start:]


def bodies(store: pathlib.Path, entries) -> dict[str, str]:
    out = {}
    for e in entries:
        p = store / e["target"]
        try:
            out[e["target"]] = p.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            out[e["target"]] = ""
    return out


def score(kw: str, entry: dict, body: str) -> int:
    stem = entry["target"][:-3].lower()
    tokens = [t for t in re.split(r"[-_.]", stem) if t]
    s = 0
    if kw in tokens:
        s += 100
    elif kw in stem:
        s += 40
    if entry["kws"] and entry["kws"][0] == kw:
        s += 30
    s += min(body.count(kw), 25)
    return s


def candidates(body: str, taken: set[str]) -> list[str]:
    found: collections.Counter[str] = collections.Counter()
    for rx in CANDIDATE_RES:
        for m in rx.finditer(body):
            tok = m.group(0).strip()
            if not (4 <= len(tok) <= 48) or tok in taken or tok in GENERIC:
                continue
            found[tok] += 1
    # Structural tokens first, then by frequency; deterministic on ties.
    return [t for t, _ in sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))]


def protected(kw: str, entry: dict, body: str) -> bool:
    """A line's core vocabulary: its filename, its first keyword, its content.

    Removing one of these to satisfy a collision turns a file about X into a
    file that no longer says X, which is worse than the collision. Generic
    words listed in OVERRIDES are exempt — they belong to the general file.
    """
    if kw in OVERRIDES:
        return False
    stem = entry["target"][:-3].lower()
    if kw in re.split(r"[-_.]", stem):
        return True
    if entry["kws"] and entry["kws"][0] == kw:
        return True
    return body.count(kw) >= 8


def resolve(entries, body_of, report_limit: int = 15, protect: bool = True,
            min_lines: int = 2):
    owners: dict[str, str] = {}
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for e in entries:
        for kw in e["kws"]:
            groups[kw].append(e)
    collisions = {k: v for k, v in groups.items() if len(v) > 1}
    if min_lines > 2:
        collisions = {k: v for k, v in collisions.items() if len(v) >= min_lines}

    for kw, group in collisions.items():
        if kw in OVERRIDES and any(e["target"] == OVERRIDES[kw] for e in group):
            owners[kw] = OVERRIDES[kw]
            continue
        ranked = sorted(group, key=lambda e: (-score(kw, e, body_of[e["target"]]), e["target"]))
        owners[kw] = ranked[0]["target"]

    removed: dict[str, list[str]] = collections.defaultdict(list)
    added: dict[str, list[str]] = collections.defaultdict(list)
    kept_global = set()
    for kw, group in groups.items():
        owner = owners.get(kw)
        for e in group:
            if owner is None or e["target"] == owner:
                kept_global.add(kw)
    floor_blocked = []
    protected_conflicts: list[tuple[str, str]] = []
    for kw, group in collisions.items():
        owner = owners[kw]
        for e in group:
            if e["target"] == owner:
                continue
            if protect and protected(kw, e, body_of[e["target"]]):
                protected_conflicts.append((e["target"], kw))
                continue
            if len(e["kws"]) > MIN_KEYWORDS:
                e["kws"].remove(kw)
                removed[e["target"]].append(kw)
                continue
            # At the floor: try to buy a slot from the file itself.
            pool = [c for c in candidates(body_of[e["target"]], kept_global | set(e["kws"]))]
            if pool:
                e["kws"].remove(kw)
                e["kws"].append(pool[0])
                kept_global.add(pool[0])
                removed[e["target"]].append(kw)
                added[e["target"]].append(pool[0])
            else:
                floor_blocked.append((e["target"], kw))

    # Any collision that survived (a floor line with no candidate) is reported.
    again = collections.defaultdict(list)
    for e in entries:
        for kw in e["kws"]:
            again[kw].append(e["target"])
    remaining = {k: v for k, v in again.items() if len(v) > 1}
    return {
        "collisions": collisions,
        "owners": owners,
        "removed": removed,
        "added": added,
        "floor_blocked": floor_blocked,
        "protected_conflicts": protected_conflicts,
        "remaining": remaining,
        "report_limit": report_limit,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, help="memories directory")
    ap.add_argument("--apply", action="store_true", help="write MEMORY.md (default: dry run)")
    ap.add_argument("--shadow", default=None, help="work on a copy of the store in this dir")
    ap.add_argument("--report", type=int, default=15, help="ownership calls to print")
    ap.add_argument("--diff", type=int, default=0, help="show the N largest rewrites")
    ap.add_argument("--no-protect", action="store_true",
                    help="resolve every collision, even when the word is core to a line")
    ap.add_argument("--min-lines", type=int, default=2,
                    help="only touch keywords shared by at least N lines (default 2)")
    args = ap.parse_args()

    src = pathlib.Path(args.store).expanduser()
    store = src
    if args.shadow:
        store = pathlib.Path(args.shadow).expanduser()
        if store.exists():
            shutil.rmtree(store)
        shutil.copytree(src, store)
        print(f"shadow: {store}")

    head, entries, body_lines = read_store(store)
    body_of = bodies(store, entries)
    total_kw = sum(len(e["kws"]) for e in entries)
    res = resolve(entries, body_of, args.report, protect=not args.no_protect,
                  min_lines=args.min_lines)
    n_coll = len(res["collisions"])
    n_removed = sum(len(v) for v in res["removed"].values())
    n_added = sum(len(v) for v in res["added"].values())
    changed = len({t for t in res["removed"]} | {t for t in res["added"]})

    print(f"lines: {len(entries)}  keywords: {total_kw}")
    print(f"collisions: {n_coll} keywords on 2+ lines")
    print(f"plan: {changed} lines rewritten, -{n_removed} / +{n_added} keywords, "
          f"{n_removed - n_added} net")
    print(f"at floor: {sum(1 for e in entries if len(e['kws']) == MIN_KEYWORDS)} lines")
    if res["floor_blocked"]:
        print(f"UNRESOLVED floor blocks: {len(res['floor_blocked'])} "
              f"{res['floor_blocked'][:6]}")
    if res["protected_conflicts"]:
        by_kw: dict[str, list[str]] = collections.defaultdict(list)
        for target, kw in res["protected_conflicts"]:
            by_kw[kw].append(target)
        print(f"protected conflicts (core words left alone): {len(by_kw)} keywords")
        for kw, targets in sorted(by_kw.items(), key=lambda kv: -len(kv[1]))[:12]:
            print(f"  {kw:24s} kept on {', '.join(sorted(targets))}")
    if res["remaining"]:
        print(f"REMAINING collisions: {len(res['remaining'])} "
              f"{list(res['remaining'].items())[:4]}")
    print(f"size: {sum(len(render(e)) for e in entries)} chars")

    top = sorted(res["collisions"].items(), key=lambda kv: -len(kv[1]))[:args.report]
    print(f"\nownership calls (top {len(top)}):")
    for kw, group in top:
        print(f"  {kw:24s} owner {res['owners'][kw]:38s} also on "
              f"{', '.join(sorted(e['target'] for e in group if e['target'] != res['owners'][kw]))}")

    if args.diff:
        rows = sorted(entries, key=lambda e: -len(res["removed"].get(e["target"], [])))
        print(f"\nlargest rewrites ({args.diff}):")
        for e in rows[:args.diff]:
            loss = res["removed"].get(e["target"], [])
            if not loss:
                continue
            gain = res["added"].get(e["target"], [])
            print(f"  {e['target']:34s} -{len(loss)}"
                  f"{' +' + str(len(gain)) if gain else ''}  "
                  f"-{','.join(loss)}" + (f"  +{','.join(gain)}" if gain else ""))
            print(f"    now: {render(e)}")

    if not args.apply:
        print("\ndry run: nothing written. Use --apply (or --shadow + --apply for a test copy).")
        return 0

    if store == src and n_coll and (res["remaining"] or res["floor_blocked"]):
        print("refusing to apply: collisions remain", flush=True)
        return 1

    out_lines = list(head)
    for e in entries:
        out_lines.append(render(e))
    backup = store / f"MEMORY.md.bak-dedupe-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(store / "MEMORY.md", backup)
    (store / "MEMORY.md").write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"\napplied; backup at {backup}")

    # Validate the result with the repo validator, tiers included.
    verify = pathlib.Path(__file__).with_name("verify_index.py")
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(verify), str(store / "MEMORY.md"),
                        "--memdir", str(store), "--keywords"],
                       capture_output=True, text=True)
    tail = [l for l in r.stdout.splitlines() if l.startswith(("keywords:", "[FAIL] KEYWORD"))]
    print("\n".join(tail[-4:]))
    print(f"validator exit: {r.returncode}")
    return 0 if res["remaining"] == {} else 1


if __name__ == "__main__":
    raise SystemExit(main())
