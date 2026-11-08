#!/usr/bin/env python3
"""Rebuild route-line keywords from the child's own content.

The author model writes good engrams but unreliable route keywords: it may put
every sibling's name on one line. This pass derives keywords from what the child
actually contains — its H1, its H2 headings, then its first paragraph — so a
line describes only its own file. Keywords stay 5–20 and unique inside the table.

    python3 scripts/rekeyword.py --store <memories> [--apply]
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

ARROW = "\u2192"
ROUTE = re.compile(r"^(?P<kw>.+?)\s*(?:\u2192|->)\s*(?P<t>[A-Za-z0-9_.\-]+\.md)\s*$")
GOOD = re.compile(r"^[a-z0-9][a-z0-9_.\-]{1,47}$")
JUNK = re.compile(r"(\.md$|^v?\d+[.\-]\d+|.{30,}-.{10,}-.{10,})")
STOP = {"the", "and", "for", "with", "from", "that", "this", "into", "when", "what", "how",
        "are", "was", "were", "has", "have", "its", "not", "but", "all", "any", "can",
        "part", "under", "moved", "md", "section", "file", "files", "detail", "project",
        "part", "note", "notes", "facts", "fact", "brief", "record", "every", "exactly",
        "since", "also", "then", "than", "them", "they", "your", "you", "its"}


def words(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9_.\-]{2,}", text.lower()):
        if w in STOP or JUNK.search(w) or not GOOD.match(w) or w.isdigit():
            continue
        if w not in out:
            out.append(w)
    return out


def derive(child: pathlib.Path) -> list[str]:
    try:
        lines = child.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    title = next((l[2:] for l in lines if l.startswith("# ")), "")
    heads = [l[3:] for l in lines if l.startswith("## ")]
    body = " ".join(l for l in lines[:40] if not l.startswith("#"))
    kws = []
    # the child's own names first: title and section headings
    for group in (title, *heads):
        for w in words(group):
            if w not in kws:
                kws.append(w)
    for w in words(body):
        if len(kws) >= 12:
            break
        if w not in kws:
            kws.append(w)
    return kws[:20]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    store = pathlib.Path(args.store).expanduser()
    changed = 0
    for path in sorted(store.glob("*.md")):
        if path.name in {"MEMORY.md", "USER.md"}:
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        body = [l for l in lines if l.strip() and not l.strip().startswith("#")]
        routes = [l for l in body if ROUTE.match(l)]
        if not routes or len(routes) / max(1, len(body)) < 0.5:
            continue
        used: set[str] = set()
        out, hits = [], 0
        for line in lines:
            m = ROUTE.match(line.strip())
            if not m:
                out.append(line)
                continue
            child = store / m.group("t")
            kws = [k for k in derive(child) if k not in used]
            if len(kws) < 5:
                for w in words(m.group("t")[:-3].replace("-", " ")):
                    if len(kws) >= 5:
                        break
                    if w not in used and w not in kws:
                        kws.append(w)
            for filler in ("detail", "notes", "state", "values", "context"):
                if len(kws) >= 5:
                    break
                if filler not in used and filler not in kws:
                    kws.append(filler)
            kws = kws[:20]
            used.update(kws)
            new = " ".join(kws) + f" {ARROW} " + m.group("t")
            if new != line.strip():
                hits += 1
            out.append(new)
        if hits:
            changed += hits
            print(f"{path.name}: {hits} line(s)")
            if args.apply:
                path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{changed} route line(s) rewritten")
    if args.apply:
        verify = pathlib.Path(__file__).with_name("verify_index.py")
        r = subprocess.run([sys.executable, str(verify), str(store / "MEMORY.md"), "--memdir", str(store),
                            "--tree", "--keywords"], capture_output=True, text=True)
        for l in r.stdout.splitlines():
            if l.startswith(("  [FAIL]", "tree:", "keywords:")) or re.match(r"^\d+ lines", l):
                print(l)
        print("validator exit:", r.returncode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
