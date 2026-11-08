#!/usr/bin/env python3
"""Convert neurons into pure keyword routers.

Before: a neuron carried `keywords: ...` plus a `## Related memories` block of
`- when <condition> → child.md` bullets, and engrams carried their own
`keywords:` line.

After: a neuron is a table of route lines, exactly like the index —

    keyword,keyword,keyword,keyword,keyword → child.md

and the child's keywords live on the line that points at it. Engrams lose their
`keywords:` header (their identity is their parent's route line) and keep only
the memory text.
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
EDGE = re.compile(r"^[-*]\s+when\s+(?P<cond>.+?)\s*(?:\u2192|->)\s*(?P<t>[A-Za-z0-9_.\-]+\.md)\s*$", re.M)
KLINE = re.compile(r"^\s*keywords:\s*(?P<k>.+)$", re.I)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    store = pathlib.Path(args.store).expanduser()

    nodes = {}
    for p in sorted(store.glob("*.md")):
        if p.name in {"MEMORY.md", "USER.md"}:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        kws = []
        for line in text.splitlines()[:4]:
            m = KLINE.match(line)
            if m:
                kws = [k.strip().lstrip("!") for k in m.group("k").split(",") if k.strip()]
                break
        nodes[p.name] = {"kws": kws, "edges": EDGE.findall(text), "text": text}

    neurons = {n: d for n, d in nodes.items() if d["edges"]}
    engrams = {n: d for n, d in nodes.items() if not d["edges"]}
    print(f"neurons: {len(neurons)}  engrams: {len(engrams)}")

    def derive(name: str, cond: str) -> list[str]:
        words = re.findall(r"[a-z][a-z0-9_.\-/]{3,}", (cond + " " + name).lower())
        stop = {"when", "question", "about", "that", "this", "with", "from", "asks"}
        out = []
        for w in words:
            if w in stop or w in out:
                continue
            out.append(w)
        return out[:20]

    plan = {}
    for name, d in neurons.items():
        lines, used = [], set()
        for cond, child in d["edges"]:
            kws = [k for k in (nodes.get(child, {}).get("kws") or []) if k not in used]
            if len(kws) < 5:
                kws = (kws + [w for w in derive(child, cond) if w not in kws])[:20]
            kws = kws[:20]
            if len(kws) < 5:
                print(f"  WARN {name} -> {child}: only {len(kws)} keywords", file=sys.stderr)
            used.update(kws)
            lines.append(f"{' '.join(kws)} {ARROW} {child}")
        plan[name] = lines

    for name, lines in plan.items():
        print(f"\n{name}")
        for l in lines:
            print("  " + l[:160])

    if not args.apply:
        print("\ndry run: nothing written.")
        return 0

    backup = store / f"routes-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    shutil.copytree(store, backup, ignore=shutil.ignore_patterns("*.bak*", "deepen-*",
                                                                 "split-families-*", "routerize-*", "routes-*"))
    for name, lines in plan.items():
        (store / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name, d in engrams.items():
        lines = d["text"].splitlines()
        out = [l for l in lines if not KLINE.match(l)]
        while out and not out[0].strip():
            out.pop(0)
        (store / name).write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    print(f"\napplied; backup {backup}")

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
