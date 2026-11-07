#!/usr/bin/env python3
"""Re-seed indexed neurons' keyword lines from the final index.

The first five keywords of an index line are the locked block; the file's own
line starts with the same five, so a reseed after an index rewrite keeps the
two in step. Only files named by an index line are touched.
"""
import argparse
import pathlib
import re

ARROW = "\u2192"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    args = ap.parse_args()
    store = pathlib.Path(args.store).expanduser()
    n = 0
    for line in (store / "MEMORY.md").read_text(encoding="utf-8").splitlines():
        if ARROW not in line or line.lstrip().startswith("#"):
            continue
        kw, target = line.rsplit(ARROW, 1)
        target = target.strip()
        if not target.endswith(".md"):
            continue
        kws = [k.strip().lstrip("!") for k in kw.split(",") if k.strip()][:5]
        if len(kws) < 5:
            continue
        path = store / target
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        i = next((i for i, l in enumerate(lines) if l.strip()), None)
        if i is None:
            continue
        if lines[i].strip().lower().startswith("keywords:"):
            lines[i] = "keywords: " + ",".join(kws)
        else:
            lines.insert(i, "keywords: " + ",".join(kws))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        n += 1
    print(f"reseeded {n} indexed neurons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
