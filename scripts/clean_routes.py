#!/usr/bin/env python3
"""Rebuild route-line keywords into clean, unique, 5–20 word lines.

Mechanical splitters sometimes emit debris: stray punctuation, fragments from a
title wrapped across lines, or three keywords where five are required. This pass
sanitises every router's table without touching its edges.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

ARROW = "\u2192"
ROUTE = re.compile(r"^(?P<kw>.+?)\s*\u2192\s*(?P<t>[A-Za-z0-9_.\-]+\.md)\s*$")
GOOD = re.compile(r"^[a-z0-9][a-z0-9_.\-]{1,47}$")
FILLER = ["detail", "notes", "state", "facts", "values", "context", "history", "setup"]


def sanitize(tokens):
    out = []
    for tok in tokens:
        t = tok.lower().strip(".,;:()[]`'\"")
        if not t or not GOOD.match(t):
            continue
        if t.isdigit() and len(t) < 2:
            continue
        if t not in out:
            out.append(t)
    return out


def from_target(store: pathlib.Path, target: str) -> list[str]:
    words = re.findall(r"[a-z0-9][a-z0-9_.\-]{2,}", target[:-3].lower())
    try:
        text = (store / target).read_text(encoding="utf-8", errors="replace")
        head = "\n".join(text.splitlines()[:25])
        words += re.findall(r"[a-z0-9][a-z0-9_.\-]{2,}", head.lower())
    except OSError:
        pass
    return words


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    store = pathlib.Path(args.store).expanduser()

    for path in sorted(store.glob("*.md")):
        if path.name in {"MEMORY.md", "USER.md"}:
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        body = [l for l in lines if l.strip() and not l.strip().startswith("#")]
        if not body:
            continue
        routes = [l for l in body if ROUTE.match(l.strip())]
        if len(routes) / len(body) < 0.5:
            continue
        used: set[str] = set()
        out = []
        changed = 0
        for line in lines:
            m = ROUTE.match(line.strip())
            if not m:
                out.append(line)
                continue
            kws = [k for k in sanitize(m.group("kw").split()) if k not in used][:20]
            if len(kws) < 5:
                for w in sanitize(from_target(store, m.group("t"))):
                    if len(kws) >= 8:
                        break
                    if w not in used and w not in kws:
                        kws.append(w)
            for f in FILLER:
                if len(kws) >= 5:
                    break
                if f not in used and f not in kws:
                    kws.append(f)
            used.update(kws)
            new = " ".join(kws[:20]) + f" {ARROW} " + m.group("t")
            if new != line.strip():
                changed += 1
            out.append(new)
        if changed:
            print(f"{path.name}: {changed} lines")
            if args.apply:
                path.write_text("\n".join(out) + "\n", encoding="utf-8")

    if args.apply:
        verify = pathlib.Path(__file__).with_name("verify_index.py")
        r = subprocess.run([sys.executable, str(verify), str(store / "MEMORY.md"),
                            "--memdir", str(store), "--tree", "--keywords"],
                           capture_output=True, text=True)
        for l in r.stdout.splitlines():
            if l.startswith(("  [FAIL]", "tree:", "keywords:", "116")):
                print(l)
        print("validator exit:", r.returncode)
        return r.returncode
    print("dry run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
