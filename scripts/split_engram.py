#!/usr/bin/env python3
"""Split an oversized engram into sibling engrams linked from its neuron.

An engram over the 7 KB ceiling with real H2 sections is several aspects of one
subject. Each aspect becomes `<neuron>-<aspect>.md`; the neuron keeps one route
line per new file, keywords unique inside its table; the fat original is
removed once its content is distributed.
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
CEILING = 7000
CHUNK = 5500


def slug(text: str, limit: int = 34) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    stop = {"the", "and", "for", "with", "from", "that", "this", "into", "when", "what", "how"}
    out = [w for w in words if w not in stop][:5]
    return "-".join(out)[:limit] or "part"


def parse(text: str):
    lines = text.splitlines()
    title = next((l.lstrip("# ").strip() for l in lines if l.startswith("# ")), "Engram")
    sections, cur = [], None
    preamble = []
    for line in lines:
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            if cur:
                sections.append(cur)
            cur = [line, ""]
        elif cur is not None:
            cur.append(line)
        else:
            preamble.append(line)
    if cur:
        sections.append(cur)
    return title, [p for p in preamble if not p.lower().startswith("part of:")], sections


def group(sections, budget=CHUNK):
    out, cur, size = [], [], 0
    for sec in sections:
        n = len("\n".join(sec))
        if cur and size + n > budget:
            out.append(cur); cur, size = [], 0
        cur.append(sec); size += n
    if cur:
        out.append(cur)
    return out


def keywords_for(title_line: str, stem: str, used: set[str]) -> list[str]:
    words = [w for w in re.findall(r"[a-z][a-z0-9_.\-]{2,}", (title_line + " " + stem).lower())]
    kws = []
    for w in words:
        if w in used or w in kws or w.isdigit():
            continue
        kws.append(w)
    for filler in ("detail", "notes", "state", "facts", "context", "history", "setup", "values"):
        if len(kws) >= 6:
            break
        if filler not in used and filler not in kws:
            kws.append(filler)
    return kws[:20]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--file", required=True, help="engram to split")
    ap.add_argument("--neuron", required=True, help="router that links it")
    ap.add_argument("--promote", action="store_true",
                    help="the neuron does not exist yet: create it with the new routes")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    store = pathlib.Path(args.store).expanduser()
    target = args.file
    text = (store / target).read_text(encoding="utf-8", errors="replace")
    neuron_path = store / args.neuron
    neuron = neuron_path.read_text(encoding="utf-8") if neuron_path.exists() else ""

    title, preamble, sections = parse(text)
    if len(sections) < 2:
        print(f"{target}: {len(sections)} section(s) — needs a manual split")
        return 2
    groups = group(sections)
    stem = target[:-3]
    used = {k.lstrip("!") for line in neuron.splitlines()
            for m in [ROUTE.match(line.strip())] if m
            for k in m.group("kw").split()}
    plan = []
    for i, g in enumerate(groups, 1):
        head = g[0][0].lstrip("# ").strip()
        name = f"{stem}-{slug(head)}.md"
        if (store / name).exists():
            name = f"{stem}-{slug(head)}-{i}.md"
        plan.append((name, head, g))

    for name, head, g in plan:
        print(f"  {name:58s} {sum(len('\\n'.join(x)) for x in g):5d} bytes  ({head[:40]})")
    if not args.apply:
        print("dry run")
        return 0

    backup = store / f"engram-split-{time.strftime('%Y%m%d-%H%M%S')}-{target[:-3]}"
    backup.mkdir()
    shutil.copy2(store / target, backup / target)
    if neuron_path.exists():
        shutil.copy2(neuron_path, backup / args.neuron)

    body_intro = "\n".join(preamble).strip()
    for name, head, g in plan:
        content = "\n".join(x if isinstance(x, str) else "\n".join(x) for x in g)
        (store / name).write_text(f"# {head}\nPart of: {args.neuron}.\n\n{content.strip()}\n",
                                  encoding="utf-8")

    lines = []
    for line in neuron.splitlines():
        m = ROUTE.match(line.strip())
        if m and m.group("t") == target:
            for name, head, g in plan:
                kws = keywords_for(head, stem, used)
                used.update(kws)
                lines.append(f"{' '.join(kws)} {ARROW} {name}")
            continue
        lines.append(line)
    if not neuron.strip():
        for name, head, g in plan:
            kws = keywords_for(head, stem, used)
            used.update(kws)
            lines.append(f"{' '.join(kws)} {ARROW} {name}")
    neuron_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (store / target).unlink()
    print(f"split {target} -> {len(plan)} engrams; backup {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
