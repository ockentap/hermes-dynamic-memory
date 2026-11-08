#!/usr/bin/env python3
"""Make every neuron a pure keyword router.

A neuron holds a keyword line and its `when -> child` links, nothing else. Any
body text it still carries is not a router: it is moved into an engram
`<neuron>-overview.md` and linked, so the memory survives and the router is
clean. Engrams (files without links) are left alone.
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
EDGE = re.compile(r"^[-*]\s+when\s+(?P<cond>.+?)\s+(?:\u2192|->)\s*(?P<t>[A-Za-z0-9_.\-]+\.md)\s*$", re.M)
MAX_LINKS = 5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    store = pathlib.Path(args.store).expanduser()

    plan = []
    for p in sorted(store.glob("*.md")):
        if p.name in {"MEMORY.md", "USER.md"}:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        edges = EDGE.findall(text)
        if not edges:
            continue  # engram: content is the point
        lines = text.splitlines()
        kw = next((l for l in lines if l.strip().lower().startswith("keywords:")), "")
        # body = everything that is not the keyword line or the Related block
        body, in_rel = [], False
        for line in lines:
            if line.strip().lower().startswith("keywords:"):
                continue
            if re.match(r"^#{2,3}\s*related", line.strip(), re.I):
                in_rel = True
                continue
            if in_rel:
                continue
            if line.strip().startswith(("- when", "* when")):
                continue
            body.append(line)
        body_text = "\n".join(body).strip()
        plan.append({"file": p.name, "kw": kw, "edges": edges, "body": body_text})

    dirty = [x for x in plan if len(x["body"]) > 120]
    print(f"neurons: {len(plan)}, with body text to move: {len(dirty)}")
    for x in dirty:
        print(f"  {x['file']:44s} body {len(x['body']):6d} chars, {len(x['edges'])} links")
    if not args.apply:
        print("dry run: nothing written.")
        return 0

    backup = store / f"routerize-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    shutil.copytree(store, backup, ignore=shutil.ignore_patterns("*.bak*", "deepen-*", "split-families-*", "routerize-*"))
    for x in plan:
        p = store / x["file"]
        edges = list(x["edges"])
        if len(x["body"]) > 120:
            if len(edges) >= MAX_LINKS:
                print(f"  SKIP {x['file']}: already {len(edges)} links", file=sys.stderr)
                continue
            stem = p.stem
            overview = f"{stem}-overview.md"
            title = next((l.lstrip("# ").strip() for l in x["body"].splitlines() if l.startswith("#")), stem)
            words = re.findall(r"[a-z][a-z0-9_.\-/]{3,}", x["body"].lower())
            stop = {"the", "and", "for", "with", "that", "this", "from", "were", "was",
                    "hermes", "when", "then", "have", "will", "into", "over", "under"}
            taken = set()
            for _c, sib in edges:
                sp = store / sib
                if sp.exists():
                    for line in sp.read_text(encoding="utf-8", errors="replace").splitlines()[:3]:
                        if line.strip().lower().startswith("keywords:"):
                            taken.update(k.strip().lstrip("!") for k in line.split(":", 1)[1].split(",") if k.strip())
            kws_list = []
            for w in words:
                if w in taken:
                    continue
                if w in stop or w in kws_list:
                    continue
                kws_list.append(w)
                if len(kws_list) >= 8:
                    break
            kws = ",".join(kws_list) if len(kws_list) >= 5 else "overview,detail,content,memory,file"
            (store / overview).write_text(
                f"keywords: {kws}\n# {title}\nPart of: {x['file']}.\n\n{x['body']}\n", encoding="utf-8")
            edges.append((f"the question is about the detail this router introduces", overview))
        out = [x["kw"], "", "## Related memories"]
        out += [f"- when {c} \u2192 {t}" for c, t in edges]
        p.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"applied; backup {backup}")

    verify = pathlib.Path(__file__).with_name("verify_index.py")
    r = subprocess.run([sys.executable, str(verify), str(store / "MEMORY.md"), "--memdir", str(store),
                        "--tree", "--keywords"], capture_output=True, text=True)
    for l in r.stdout.splitlines():
        if l.startswith(("  [FAIL]", "tree:", "keywords:")):
            print(l)
    print(f"validator exit: {r.returncode}")
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
