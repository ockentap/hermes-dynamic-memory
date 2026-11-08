#!/usr/bin/env python3
"""Group a neuron's children under intermediate neurons (fan-out cap).

A neuron that routes to more than five children gets sub-neurons: the same route
lines move into the group file, and the parent keeps one line per group.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ARROW = "\u2192"
ROUTE = re.compile(r"^(?P<kw>.+?)\s*\u2192\s*(?P<t>[A-Za-z0-9_.\-]+\.md)\s*$")
FILLER = ["group", "detail", "notes", "state", "facts", "values"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--parent", required=True)
    ap.add_argument("--group", action="append", required=True,
                    help="name.md:child1.md,child2.md (repeatable; name may omit .md)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    store = pathlib.Path(args.store).expanduser()
    parent_path = store / args.parent
    lines = parent_path.read_text(encoding="utf-8").splitlines()
    by_target = {}
    for line in lines:
        m = ROUTE.match(line.strip())
        if m:
            by_target[m.group("t")] = line.strip()

    groups, moved = [], set()
    for spec in args.group:
        name, kids = spec.split(":", 1)
        if not name.endswith(".md"):
            name += ".md"
        kid_list = [k.strip() for k in kids.split(",") if k.strip()]
        missing = [k for k in kid_list if k not in by_target]
        if missing:
            print(f"  skip {name}: unknown children {missing}", file=sys.stderr)
            continue
        groups.append((name, kid_list))
        moved.update(kid_list)

    used = set()
    for t, line in by_target.items():
        if t in moved:
            continue
        kw = line.split(ARROW)[0]
        used.update(kw.split())

    print(f"{args.parent}: {len(by_target)} children -> {len(groups)} groups")
    for name, kids in groups:
        print(f"  {name:44s} {len(kids)} children")

    if not args.apply:
        print("dry run")
        return 0

    new_parent = []
    for line in lines:
        m = ROUTE.match(line.strip())
        if not m or m.group("t") not in moved:
            new_parent.append(line)
    for name, kids in groups:
        (store / name).write_text("\n".join(by_target[k] for k in kids) + "\n", encoding="utf-8")
        kws = [w for w in re.findall(r"[a-z][a-z0-9_.\-]{2,}", name[:-3].lower()) if w not in used]
        for k in kids:
            for w in by_target[k].split(ARROW)[0].split():
                if w not in used and w not in kws:
                    kws.append(w)
        for f in FILLER:
            if len(kws) >= 5:
                break
            if f not in used and f not in kws:
                kws.append(f)
        kws = kws[:20]
        used.update(kws)
        new_parent.append(f"{' '.join(kws)} {ARROW} {name}")
    parent_path.write_text("\n".join(new_parent) + "\n", encoding="utf-8")
    print("applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
