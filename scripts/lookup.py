#!/usr/bin/env python3
"""Walk the memory tree with bare evaluator calls.

The agent does not read the store to find a memory. It asks a bare model, one
hop at a time, and only the files at the end are read:

  index  --call-->  neuron(s)  --call-->  ...  --call-->  engram(s)

Every call gets the user's question and one node: for the index, its keyword
lines; for a neuron, its routing card. The model is bare — no persona, no tools,
no memory injection — and answers with the files it considers relevant.

    python3 lookup.py --store ~/.hermes/memories --question "openwrt relay"
    python3 lookup.py --store ... --question "..." --max-files 3 --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("MEMLOOK_BASE_URL", "https://opencode.ai/zen/go/v1")
MODEL = os.environ.get("MEMLOOK_MODEL", "deepseek-v4.1-flash")
MAX_TIER = 5

INDEX_SYSTEM = (
    "You are a memory router. You get a keyword index, one line per memory, and "
    "a question. Reply with JSON only: {\"files\":[\"<name>.md\", ...]} listing at "
    "most {n} entries whose keyword set best matches the question. Use the exact "
    "filenames after the arrow. No prose, no explanation."
)
NODE_SYSTEM = (
    "You are a memory router. You get one routing table and a question. Each line "
    "is '<keywords> → <child.md>'. Reply with JSON only: "
    "{\"files\":[\"<name>.md\", ...]} listing at most {n} children whose keywords "
    "best match the question. No prose."
)
EDGE = re.compile(r"^[-*]\s+when\s+(?P<cond>.+?)\s+(?:\u2192|->)\s+(?P<target>[A-Za-z0-9_.\-]+\.md)\s*$", re.M)


def load_key() -> str:
    for n in ("OPENCODE_GO_API_KEY", "OPENAI_API_KEY"):
        if os.environ.get(n):
            return os.environ[n]
    for p in (os.path.expanduser("~/.hermes/profiles/vps/.env"), os.path.expanduser("~/.hermes/.env")):
        if os.path.exists(p):
            for line in open(p, encoding="utf-8", errors="ignore"):
                m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*)", line)
                if m and m.group(1) in ("OPENCODE_GO_API_KEY", "OPENAI_API_KEY"):
                    return m.group(2).strip().strip('"').strip("'")
    raise SystemExit("no API key: set OPENCODE_GO_API_KEY")


def call(system: str, user: str, max_tokens: int = 1200) -> tuple[str, int]:
    key = load_key()
    body = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
            "reasoning_effort": "none",
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}
    req = urllib.request.Request(
        BASE.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "x-opencode-session": "memlook-" + os.urandom(4).hex(),
                 "User-Agent": "dynmem-lookup/1.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.load(r)
    ch = d["choices"][0]
    text = ch["message"].get("content") or ""
    if not text and ch.get("finish_reason") == "length" and max_tokens < 3000:
        return call(system, user, 3000)
    return text, int((d.get("usage") or {}).get("total_tokens", 0))


def parse_files(text: str) -> list[str]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    files = data.get("files") or []
    if isinstance(files, str):
        files = [files]
    return [f for f in files if isinstance(f, str) and f.endswith(".md")]


def index_text(store) -> tuple[str, dict[str, list[str]]]:
    """Compact router view: 'target: kw kw kw'. Commas and arrows are one token
    each in most tokenizers; dropping them shaves ~25% off the first call."""
    lines, table = [], {}
    for line in (store / "MEMORY.md").read_text(encoding="utf-8").splitlines():
        if "\u2192" not in line or line.lstrip().startswith("#"):
            continue
        kw, target = line.rsplit("\u2192", 1)
        target = target.strip()
        if not target.endswith(".md"):
            continue
        kws = [k.strip().lstrip("!") for k in re.split(r"[,\s]+", kw) if k.strip()]
        lines.append(target + ": " + " ".join(kws))
        table[target] = kws
    return "\n".join(lines), table


ROUTE = re.compile(r"^(?P<kw>.+?)\s*(?:\u2192|->)\s*(?P<t>[A-Za-z0-9_.\-]+\.md)\s*$", re.M)


def children(store, name: str) -> list[str]:
    p = store / name
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    if not all(ROUTE.match(l) or EDGE.match(l) for l in lines):
        return []          # a content file, not a router
    return [m.group("t") for m in ROUTE.finditer(text)] + [m.group("target") for m in EDGE.finditer(text)]


def walk(store, question: str, max_files: int):
    index, _ = index_text(store)
    stats = {"calls": 0, "tokens": 0}
    hops = []

    def ask(system: str, body: str) -> list[str]:
        text, tok = call(system.replace("{n}", str(max_files)), body)
        stats["calls"] += 1
        stats["tokens"] += tok
        return parse_files(text)[:max_files]

    picked = ask(INDEX_SYSTEM, f"INDEX:\n{index}\n\nQUESTION: {question}")
    hops.append(("index", picked))
    frontier, visited, engrams = [(f, 2) for f in picked], set(picked), []
    while frontier:
        name, tier = frontier.pop(0)
        kids = children(store, name)
        if not kids:
            engrams.append(name)
            continue
        if tier >= MAX_TIER:
            engrams.append(name)
            continue
        card = (store / name).read_text(encoding="utf-8", errors="replace")
        got = ask(NODE_SYSTEM, f"CARD:\n{card[:6000]}\n\nQUESTION: {question}")
        hops.append((name, got))
        for child in got:
            if child not in visited and (store / child).exists():
                visited.add(child)
                frontier.append((child, tier + 1))
    return engrams, hops, stats


SHEET_SYSTEM = (
    "You are a memory router. You get a keyword index and the routing cards of "
    "the memories that have children. Each index line is '<keywords> -> <file.md>'. "
    "Each card lists '<when condition> \u2192 <child.md>'. Follow the cards yourself "
    "and reply with JSON only: {\"files\":[\"<name>.md\", ...]} naming at most {n} "
    "ENGRAM files (files that appear as a target and have no card of their own) "
    "which contain the answer. No prose."
)


def routing_sheet(store) -> str:
    idx, cards = [], []
    for line in (store / "MEMORY.md").read_text(encoding="utf-8").splitlines():
        if "\u2192" in line and not line.lstrip().startswith("#"):
            kw, target = line.rsplit("\u2192", 1)
            if target.strip().endswith(".md"):
                idx.append(target.strip() + ": " +
                           " ".join(k.strip().lstrip("!") for k in re.split(r"[,\s]+", kw) if k.strip()))
    for path in sorted(store.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        edges = EDGE.findall(text)
        if edges:
            cards.append("## " + path.name + "\n"
                         + "\n".join(f"- when {c} \u2192 {t}" for c, t in edges))
    return ("INDEX\n" + "\n".join(idx) + "\n\nROUTING CARDS\n" + "\n\n".join(cards))


def walk_sheet(store, question: str, max_files: int):
    sheet = routing_sheet(store)
    text, tok = call(SHEET_SYSTEM.replace("{n}", str(max_files)),
                     f"{sheet}\n\nQUESTION: {question}", max_tokens=400)
    picked = parse_files(text)[:max_files]
    return picked, [("sheet", picked)], {"calls": 1, "tokens": tok}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--question", required=True)
    ap.add_argument("--max-files", type=int, default=3)
    ap.add_argument("--sheet", action="store_true",
                    help="one call: index + every routing card in one prompt (lowest request count)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--read", action="store_true",
                    help="print the engram text, which is what the caller feeds back")
    ap.add_argument("--max-chars", type=int, default=0,
                    help="cap per file when --read is used (0 = whole file)")
    args = ap.parse_args()
    store = __import__("pathlib").Path(args.store).expanduser()
    if args.sheet:
        engrams, hops, stats = walk_sheet(store, args.question, args.max_files)
    else:
        engrams, hops, stats = walk(store, args.question, args.max_files)
    if args.json:
        print(json.dumps({"question": args.question, "files": engrams, "hops": hops,
                          "calls": stats["calls"], "router_tokens": stats["tokens"]}, indent=1))
    else:
        for name, picked in hops:
            print(f"  {name:34s} -> {', '.join(picked) or '(none)'}")
        print(f"read: {', '.join(engrams) or '(none)'}")
        print(f"router: {stats['calls']} calls, {stats['tokens']} tokens")
        if args.read:
            for name in engrams:
                text = (store / name).read_text(encoding="utf-8", errors="replace")
                if args.max_chars:
                    text = text[:args.max_chars]
                print(f"\n===== {name} =====\n{text}")
    return 0 if engrams else 1


if __name__ == "__main__":
    raise SystemExit(main())
