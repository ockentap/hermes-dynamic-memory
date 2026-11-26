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


def parse(text: str, marker: str = '## '):
    lines = text.splitlines()
    title = next((l.lstrip("# ").strip() for l in lines if l.startswith("# ")), "Engram")
    sections, cur = [], None
    preamble = []
    for line in lines:
        if line.startswith("# "):
            continue
        if line.startswith(marker) and not line.startswith(marker + '#'):
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


def plan_groups(sections, budget=CHUNK):
    """Group sections into file-sized chunks, splitting a section that alone
    exceeds the budget.

    Splitting on H2 only works while every H2 is small. One 22 KB "Gotchas"
    section produced a 22 KB 'part', so an oversized section is now chunked at
    paragraph boundaries and each chunk keeps the heading with a '— part N'
    suffix, which also makes its filename unique.
    """
    units = []
    for sec in sections:
        text = "\n".join(sec)
        if len(text) <= budget * 1.5:
            units.append(sec)
            continue
        head, body = sec[0], sec[1:]
        blocks = [p for p in "\n".join(body).split("\n\n") if p.strip()]
        # a bullet list with no blank lines is one huge "paragraph": fall back
        # to line chunks so the section can still be cut
        if len(blocks) == 1 and len(blocks[0]) > budget:
            lines = body
            blocks, cur, size = [], [], 0
            for line in lines:
                if cur and size + len(line) > budget:
                    blocks.append("\n".join(cur))
                    cur, size = [], 0
                cur.append(line.rstrip("\n"))
                size += len(line) + 1
            if cur:
                blocks.append("\n".join(cur))
        # any single block still over budget (one dense paragraph, a long
        # code fence) is cut by lines so no part can exceed the ceiling
        fixed = []
        for b in blocks:
            if len(b) <= budget:
                fixed.append(b)
                continue
            cur, size2 = [], 0
            for line in b.split("\n"):
                if cur and size2 + len(line) > budget:
                    fixed.append("\n".join(cur))
                    cur, size2 = [], 0
                cur.append(line)
                size2 += len(line) + 1
            if cur:
                fixed.append("\n".join(cur))
        blocks = fixed
        part, size, n = [], 0, 0
        for para in blocks:
            if part and size + len(para) > budget:
                n += 1
                units.append([f"{head} — part {n}", ""] + part)
                part, size = [], 0
            part.append(para + "\n")
            size += len(para) + 2
        if part:
            n += 1
            units.append([head if n == 1 else f"{head} — part {n}", ""] + part)
    return group(units, budget)


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
    # a heading can exhaust the shared pool ("Gotchas — part 2" after part 1):
    # derive stable tokens from the heading's last word + digit so the line
    # still carries 5 keywords instead of coming out empty
    if len(kws) < 5:
        tail = [w for w in re.findall(r"[a-z]+", title_line.lower()) if w not in used]
        digit = re.search(r"(\d+)\s*$", title_line or "")
        for base in tail[-2:] or ["part"]:
            for n in ([digit.group(1)] if digit else []) + [str(i) for i in range(2, 9)]:
                tok = f"{base}{n}"
                if tok not in used and tok not in kws:
                    kws.append(tok)
                if len(kws) >= 5:
                    break
            if len(kws) >= 5:
                break
    while len(kws) < 5:
        kws.append(f"part{len(kws) + 1}")
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
        # a file whose only structure is H3 under one H2 still splits
        t3, p3, s3 = parse(text, marker="### ")
        if len(s3) >= 2:
            title, preamble, sections = t3, p3, s3
    if len(sections) < 2:
        # last resort: cut the body itself. A long narrative with no headings is
        # still too big for one engram; plan_groups chunks it by paragraph/line.
        body = [l for l in text.splitlines()[1:] if not l.lower().startswith("part of:")]
        sections = [[f"## {title}", ""] + body]
        print(f"{target}: no headings — cutting the body into parts")
    groups = plan_groups(sections)
    stem = target[:-3]
    used = {k.lstrip("!") for line in neuron.splitlines()
            for m in [ROUTE.match(line.strip())] if m
            for k in m.group("kw").split()}
    plan, seen = [], {}
    for i, g in enumerate(groups, 1):
        head = g[0][0].lstrip("# ").strip()
        base = f"{stem[:34]}-{slug(head)}.md"
        seen[base] = seen.get(base, 0) + 1
        name = base if seen[base] == 1 else f"{base[:-3]}-{seen[base]}.md"
        if (store / name).exists():
            name = f"{base[:-3]}-{i}.md"
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
