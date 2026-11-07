#!/usr/bin/env python3
"""Deepen one memory file: turn it into a routing card plus small engrams.

`--file` names the neuron to split. Its H2 sections are grouped into chunks of
about `--target` characters (five engrams at most), each chunk becomes
`<parent>-<slug>.md` with its own keyword line, and the original file keeps its
index line and becomes the card that links to them. Text is moved verbatim.

Dry-run prints the plan; `--apply` backs up the store, writes, and validates
with `verify_index.py --tree --keywords`.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

ARROW = "\u2192"
MAX_ENGRAMS = 5
STOP = set("""the and for with from this that have will when then than they them their which
while what were your should could would about after before because other into file files line
lines note notes true false none work works working used using make made need needs same only
also very much more most some such here does done each both must over under again check checked
value values thing things case cases memory memories index keyword keywords read first last new
old one two all any not you are was were been being has had its it's don't doesn't""".split())


def sections(text: str):
    lines = text.splitlines()
    head, idx = [], 0
    while idx < len(lines) and not lines[idx].startswith("## "):
        head.append(lines[idx])
        idx += 1
    out, cur, buf = [], None, []
    for line in lines[idx:]:
        if line.startswith("## "):
            if cur is not None:
                out.append((cur, buf))
            cur, buf = line[3:].strip(), []
        else:
            buf.append(line)
    if cur is not None:
        out.append((cur, buf))
    return "\n".join(head).rstrip(), out


def group(secs, target: int, max_engrams: int = MAX_ENGRAMS):
    groups, cur, size = [], [], 0
    for heading, body in secs:
        chunk = (heading, body)
        n = len(heading) + sum(len(l) + 1 for l in body)
        if cur and (size + n > target or len(cur) >= 8):
            groups.append(cur)
            cur, size = [], 0
        cur.append(chunk)
        size += n
    if cur:
        groups.append(cur)
    while len(groups) > max_engrams:
        target = int(target * 1.4)
        groups, cur, size = [], [], 0
        for heading, body in secs:
            n = len(heading) + sum(len(l) + 1 for l in body)
            if cur and size + n > target:
                groups.append(cur)
                cur, size = [], 0
            cur.append((heading, body))
            size += n
        if cur:
            groups.append(cur)
    return groups


def slugify(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    stop_extra = {"the", "and", "for", "with", "that", "this", "from", "was", "were"}
    keep = [w for w in words if w not in stop_extra][:4]
    return "-".join(keep) or "part"


def keywords_for(heading: str, body: str, taken: set[str]) -> list[str]:
    text = (heading + " " + " ".join(body[:40])).lower()
    cands: list[str] = []
    for rx in (r"\b(?:[\w.-]+/){2,6}[\w.-]+\b", r"\b[a-z0-9]+(?:_[a-z0-9]+)+\b",
               r"\b[a-z][a-z0-9]*(?:\.[a-z0-9]+){2,}\b"):
        cands += re.findall(rx, text)
    words = [w for w in re.findall(r"[a-z][a-z0-9-]{3,}", text) if w not in STOP]
    cands += words + [w for w in words if w in heading.lower()]
    out: list[str] = []
    for c in cands:
        c = c.strip("-_.")
        if not c or len(c) > 48 or c in taken or c in out:
            continue
        out.append(c)
        if len(out) >= 8:
            break
    # top up from the heading so every engram has at least five
    for w in re.findall(r"[a-z][a-z0-9-]{2,}", heading.lower()):
        if len(out) >= 5:
            break
        if w not in STOP and w not in taken and w not in out:
            out.append(w)
    return out[:10]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--target", type=int, default=7000, help="bytes per engram")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    store = pathlib.Path(args.store).expanduser()
    parent = (store / pathlib.Path(args.file).name)
    text = parent.read_text(encoding="utf-8")
    existing = re.findall(r"- when .*?\u2192 ([\w.\-]+\.md)", text)
    preamble, secs = sections(text)
    secs = [x for x in secs if not x[0].lower().startswith("related")]
    if not secs:
        print("no H2 sections; nothing to split", file=sys.stderr)
        return 1
    groups = group(secs, args.target, max(1, MAX_ENGRAMS - len(existing)))

    stem = parent.stem
    plan, taken = [], set()   # sibling keywords must not repeat inside one table
    for grp in groups:
        heading = grp[0][0]
        slug = slugify(heading)
        name = f"{stem}-{slug}.md"
        while name in taken:
            name = f"{stem}-{slug}-2.md"
        taken.add(name)
        kws = keywords_for(heading, [l for _, b in grp for l in b], taken)
        taken.update(kws)
        when = " ".join(heading.replace("—", " ").split())
        if len(when.split()) < 4:
            first = next((l.strip(" -*") for _, body in grp for l in body if l.strip()), "")
            when = f"{when}: {' '.join(first.split())[:80]}"
        when = when[:110]
        plan.append({"file": name, "heading": heading, "sections": grp,
                     "keywords": kws, "when": when})

    total = sum(len(g["sections"]) for g in plan)
    print(f"{parent.name}: {len(secs)} sections -> {len(plan)} engrams "
          f"({parent.stat().st_size/1024:.1f} KB)")
    for p in plan:
        size = len(p["heading"]) + sum(len(l) + 1 for _, b in p["sections"] for l in b)
        print(f"  {p['file']:46s} {size/1024:5.1f} KB  {len(p['sections'])} sec  "
              f"kw {','.join(p['keywords'][:5])}")

    if not args.apply:
        print("dry run: nothing written.")
        return 0

    backup = store / f"deepen-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    shutil.copytree(store, backup, ignore=shutil.ignore_patterns("*.bak*", "split-families-*",
                                                                 "deepen-*"))
    index_path = store / "MEMORY.md"
    line = next((l for l in index_path.read_text(encoding="utf-8").splitlines()
                 if l.rstrip().endswith(ARROW + " " + parent.name)), None)
    if line:
        kws = line.rsplit(ARROW, 1)[0].strip()
    else:
        # A child neuron has no index line; its own keyword line is the block.
        first = next((l for l in text.splitlines() if l.strip()), "")
        if not first.lower().startswith("keywords:"):
            print(f"{parent.name} has no index line and no keyword line", file=sys.stderr)
            return 1
        kws = first.split(":", 1)[1].strip()

    for p in plan:
        body = [f"keywords: {','.join(p['keywords'])}", f"# {p['heading']}",
                f"Part of: {parent.name}.", ""]
        for heading, lines in p["sections"]:
            body.append(f"## {heading}")
            body.extend(lines)
        (store / p["file"]).write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")

    card = [f"keywords: {kws}", f"# {parent.stem.replace('-', ' ').title()} — routing card", ""]
    intro = "\n".join(preamble.splitlines()[1:]).strip()
    if intro:
        card += [intro[:600], ""]
    card.append("## Related memories")
    card += [f"- when {w} \u2192 {f}" for w, f in
             re.findall(r"- when (.*?) \u2192 ([\w.\-]+\.md)", text)]
    for p in plan:
        card.append(f"- when {p['when']} → {p['file']}")
    parent.write_text("\n".join(card) + "\n", encoding="utf-8")
    print(f"applied; backup {backup}")

    verify = pathlib.Path(__file__).with_name("verify_index.py")
    r = subprocess.run([sys.executable, str(verify), str(index_path), "--memdir", str(store),
                        "--tree", "--keywords"], capture_output=True, text=True)
    for l in r.stdout.splitlines():
        if l.startswith(("  [FAIL]", "tree:", "keywords:")):
            print(l)
    print(f"validator exit: {r.returncode}")
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
