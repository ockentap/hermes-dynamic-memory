#!/usr/bin/env python3
"""Split an engram at explicit line ranges into aspect engrams.

Use when the file has no usable H2 structure but the content still divides into
subjects. Each range becomes `<stem>-<name>.md`; the neuron's route line for the
original is replaced by one line per child; the original is removed.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import sys
import time

ARROW = "\u2192"
ROUTE = re.compile(r"^(?P<kw>.+?)\s*(?:\u2192|->)\s*(?P<t>[A-Za-z0-9_.\-]+\.md)\s*$")


def title_of(lines: list[str], fallback: str) -> str:
    for line in lines:
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^-\s+\*\*(.+?)\*\*", s)
        if m:
            return m.group(1).rstrip(".:")[:90]
        if s.startswith("#"):
            return s.lstrip("# ").strip()[:90]
        return s[:90]
    return fallback


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--neuron", required=True)
    ap.add_argument("--ranges", required=True,
                    help="name:start-end[,name:start-end]  (1-based, inclusive)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    store = pathlib.Path(args.store).expanduser()
    text = (store / args.file).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    neuron_path = store / args.neuron
    neuron = neuron_path.read_text(encoding="utf-8")

    specs = []
    for part in args.ranges.split(","):
        name, span = part.split(":")
        start, end = (int(x) for x in span.split("-"))
        chunk = lines[start - 1:end]
        specs.append((name.strip(), start, end, chunk))
        print(f"  {args.file[:-3]}-{name.strip()}.md  lines {start}-{end}  "
              f"{sum(len(l) + 1 for l in chunk)} bytes  | {title_of(chunk, name)[:60]}")

    if not args.apply:
        print("dry run")
        return 0

    backup = store / f"ranges-{time.strftime('%Y%m%d-%H%M%S')}-{args.file[:-3]}"
    backup.mkdir()
    shutil.copy2(store / args.file, backup / args.file)
    shutil.copy2(neuron_path, backup / args.neuron)

    stem = args.file[:-3]
    new_names = []
    for name, start, end, chunk in specs:
        child = f"{stem}-{name}.md"
        new_names.append(child)
        body = "\n".join(chunk).strip()
        (store / child).write_text(f"# {title_of(chunk, name)}\nPart of: {args.neuron}.\n\n{body}\n",
                                   encoding="utf-8")

    used = set()
    out = []
    for line in neuron.splitlines():
        m = ROUTE.match(line.strip())
        if m and m.group("t") == args.file:
            for name, start, end, chunk in specs:
                kws = [w for w in re.findall(r"[a-z][a-z0-9_.\-]{2,}", name.lower())]
                kws += [w for w in re.findall(r"[a-z][a-z0-9_.\-]{2,}", title_of(chunk, name).lower())
                        if w not in kws][:6]
                kws = [k for k in kws if k not in used][:20]
                for f in ("detail", "notes", "state", "facts", "values", "context"):
                    if len(kws) >= 5:
                        break
                    if f not in used and f not in kws:
                        kws.append(f)
                used.update(kws)
                out.append(f"{' '.join(kws)} {ARROW} {stem}-{name}.md")
            continue
        out.append(line)
    neuron_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    (store / args.file).unlink()
    print(f"split into {len(specs)}; backup {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
