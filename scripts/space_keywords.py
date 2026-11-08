#!/usr/bin/env python3
"""Space-delimited keywords, and no glued slash words.

Every routing table — MEMORY.md and every neuron — becomes

    keyword keyword keyword → child.md

A token containing a slash is a path only if it looks like one (it has a file
extension or a hidden segment); otherwise the slash was glue and the token is
split into separate keywords. Anything that falls under five keywords is topped
up from the target's own name so the floor still holds.
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
ROUTE = re.compile(r"^(?P<kw>.+?)\s*(?:\u2192|->)\s*(?P<t>[A-Za-z0-9_.\-]+\.md)\s*$")
MARK = re.compile(r"^(?P<m>!{1,3})(?P<k>.+)$")
PATHY = re.compile(r"\.[A-Za-z0-9]|/\.")


def clean(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if "/" in tok and not PATHY.search(tok):
            parts = [p for p in tok.split("/") if p]
            for p in parts:
                if len(p) >= 3 and not p.isdigit() and p not in out:
                    out.append(p)
        elif tok not in out:
            out.append(tok)
    return out


def topup(kws: list[str], target: str, store: pathlib.Path) -> list[str]:
    if len(kws) >= 5:
        return kws
    extra = [w for w in re.findall(r"[a-z][a-z0-9_.\-]{2,}", target[:-3].lower())
             if w not in kws]
    try:
        text = (store / target).read_text(encoding="utf-8", errors="replace")
        extra += [w for w in re.findall(r"[a-z][a-z0-9_.\-/]{3,}", text.lower())
                  if w not in kws]
    except OSError:
        pass
    for w in extra:
        if len(kws) >= 5:
            break
        if w.isdigit() or "/" in w and not PATHY.search(w):
            continue
        if w not in kws:
            kws.append(w)
    return kws


def convert_line(line: str, store: pathlib.Path) -> str | None:
    m = ROUTE.match(line.strip())
    if not m:
        return None
    kw_part, target = m.group("kw"), m.group("t")
    marker = ""
    raw = [t for t in re.split(r"[,\s]+", kw_part) if t]
    if raw:
        mm = MARK.match(raw[0])
        if mm:
            marker, raw[0] = mm.group("m"), mm.group("k")
    kws = topup(clean(raw), target, store)
    if marker:
        kws[0] = marker + kws[0]
    return " ".join(kws) + " " + ARROW + " " + target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    store = pathlib.Path(args.store).expanduser()

    files = ["MEMORY.md"] + [p.name for p in sorted(store.glob("*.md"))
                             if p.name not in {"MEMORY.md", "USER.md"}]
    changed = {}
    for name in files:
        p = store / name
        text = p.read_text(encoding="utf-8", errors="replace")
        out, hits, used = [], 0, set()
        for line in text.splitlines():
            if line.strip().startswith(("keyword,keyword", "keyword keyword")):
                out.append(line); continue
            new = convert_line(line, store) if (ARROW in line or "->" in line) else None
            if new:
                head, target = new.rsplit(ARROW, 1)
                kws = head.split()
                marker = kws[0][:3] if kws and kws[0].startswith("!") else ""
                base = [(k.lstrip("!")) for k in kws]
                kept = [k for k in base if k not in used]
                if len(kept) < 5:
                    kept = base  # leave duplicates only when the floor needs them
                if marker:
                    kept[0] = marker + kept[0]
                used.update(k.lstrip("!") for k in kept)
                new = " ".join(kept) + " " + ARROW + target
            if new and new != line.strip():
                hits += 1
                out.append(new)
            else:
                out.append(line)
        if hits:
            changed[name] = (hits, out)

    print(f"files to rewrite: {len(changed)}  routes: {sum(v[0] for v in changed.values())}")
    for name, (hits, _) in sorted(changed.items(), key=lambda kv: -kv[1][0])[:8]:
        print(f"  {name:46s} {hits}")

    if not args.apply:
        print("dry run: nothing written.")
        return 0

    backup = store / f"spaces-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    shutil.copytree(store, backup, ignore=shutil.ignore_patterns("*.bak*", "deepen-*",
                                                                 "split-families-*", "routerize-*",
                                                                 "routes-*", "spaces-*"))
    for name, (_, out) in changed.items():
        (store / name).write_text("\n".join(out) + "\n", encoding="utf-8")
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
