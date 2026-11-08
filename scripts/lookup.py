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
import math
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("MEMLOOK_BASE_URL", "https://opencode.ai/zen/go/v1")
MODEL = os.environ.get("MEMLOOK_MODEL", "deepseek-v4.1-flash")
MAX_TIER = 5
LOCAL_HOPS = False
TRIM_READS = False   # read whole engrams: trimming can drop the needed detail   # keyword-only hop selection is not reliable enough yet

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


CALLS = 0


def call(system: str, user: str, max_tokens: int = 1200,
         reasoning: str | None = "none") -> tuple[str, int]:
    global CALLS
    CALLS += 1
    key = load_key()
    body = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
            **({"reasoning_effort": reasoning} if reasoning else {}),
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
        if " — " in line and line.strip().endswith(".") and "\u2192" not in line:
            m = re.match(r"\s*([A-Za-z0-9_.\-]+\.md)\s+—\s+(.+)", line)
            if m:
                lines.append(m.group(1) + ": " + m.group(2).rstrip("."))
            continue
        if "\u2192" not in line:
            continue
        kw, target = line.rsplit("\u2192", 1)
        target = target.strip()
        if not target.endswith(".md"):
            continue
        kws = [k.strip().lstrip("!") for k in re.split(r"[,\s]+", kw) if k.strip()]
        lines.append(" ".join(kws) + " \u2192 " + target)
        table[target] = kws
    return "\n".join(lines), table


def _lexical_scores(store, question: str) -> list[tuple[float, str]]:
    """Score index lines AND header references by IDF-weighted keyword overlap.

    A rare word ("basalt-2") must outrank a common one ("reports"), otherwise a
    question phrased with ordinary verbs routes to whichever memory happens to
    use that verb.
    """
    words = set(re.findall(r"[a-z0-9][a-z0-9_.\-/]{2,}", question.lower()))
    scored: list[tuple[float, str]] = []
    route_lines = [l for l in (store / "MEMORY.md").read_text(encoding="utf-8", errors="replace").splitlines()
                   if "\u2192" in l and not l.lstrip().startswith("#")]
    df: dict[str, int] = {}
    for l in route_lines:
        for k in set(l.rsplit("\u2192", 1)[0].split()):
            df[k] = df.get(k, 0) + 1
    n = max(1, len(route_lines))
    for line in (store / "MEMORY.md").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lstrip().startswith("#") and " — " in line and line.strip().endswith("."):
            # header reference: 'name.md — what it is. Read when …'
            m = re.match(r"\s*([A-Za-z0-9_.\-]+\.md)\s+—\s+(.+)", line)
            if m:
                score = sum(1 for k in re.findall(r"[a-z][a-z0-9_.\-]{2,}", m.group(2).lower())
                            if k in words)
                if score:
                    scored.append((score, m.group(1)))
            continue
        if "\u2192" not in line:
            continue
        kw, target = line.rsplit("\u2192", 1)
        target = target.strip()
        if not target.endswith(".md"):
            continue
        kws = [k.strip().lstrip("!") for k in re.split(r"[,\s]+", kw) if k.strip()]
        score = sum(math.log(1 + n / df.get(k, 1)) for k in kws
                    if k in words or (len(k) > 3 and k in question.lower()))
        if score:
            scored.append((score, target))
    scored.sort(key=lambda x: -x[0])
    return scored


def smart_start(store, question: str, min_score: int = 2, limit: int = 2):
    """Free T1 when the lexical match is clear; None (pay for a call) when not."""
    scored = _lexical_scores(store, question)
    if not scored:
        return None
    top = scored[0][0]
    second = scored[1][0] if len(scored) > 1 else 0
    if top >= min_score and top > second:
        return [t for s_, t in scored if s_ == top][:limit]
    return None


def lexical_pick(store, question: str, limit: int = 2) -> list[str]:
    """T1 without a model call: score index lines by keyword overlap.

    The main agent already has the index in its prompt; when the script has to
    start on its own, this is the free approximation of that pick.
    """
    scored = _lexical_scores(store, question)
    if not scored:
        return []
    top = scored[0][0]
    return [t for score, t in scored if score == top][:limit]


ROUTE = re.compile(r"^(?P<kw>.+?)\s*(?:\u2192|->)\s*(?P<t>[A-Za-z0-9_.\-]+\.md)\s*$", re.M)


def card_with_titles(store, name: str) -> str:
    """Route lines plus each child's H1, so the router sees what the file is.

    The keyword line is the identity; the title disambiguates siblings whose
    keywords overlap. Files are untouched — this is prompt-side only.
    """
    out = []
    for line in (store / name).read_text(encoding="utf-8", errors="replace").splitlines():
        m = ROUTE.match(line.strip())
        if not m:
            out.append(line)
            continue
        child = store / m.group("t")
        title = ""
        if child.exists():
            for l in child.read_text(encoding="utf-8", errors="replace").splitlines()[:3]:
                if l.startswith("# "):
                    title = l[2:].strip()[:80]
                    break
        out.append(line.strip() + (("  — " + title) if title else ""))
    return "\n".join(out)


_DOCS: dict[str, dict] = {}
_STOP = {"the", "and", "for", "with", "from", "that", "this", "into", "when", "what",
         "which", "how", "are", "was", "were", "has", "have", "its", "not", "but",
         "all", "any", "can", "does", "did", "is", "it", "of", "to", "in", "on", "at",
         "be", "by", "or", "as", "an", "a"}


def _docs(store) -> dict:
    """Token counts per engram, cached per store (routers excluded)."""
    key = str(pathlib.Path(store).resolve())
    if key in _DOCS:
        return _DOCS[key]
    docs = {}
    for p in pathlib.Path(store).glob("*.md"):
        if p.name in {"MEMORY.md", "USER.md"}:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        body = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
        if body and sum(1 for l in body if ROUTE.match(l)) / len(body) >= 0.5:
            continue
        toks = {}
        for t in re.findall(r"[a-z0-9][a-z0-9_.\-/]{2,}", text.lower()):
            toks[t] = toks.get(t, 0) + 1
        docs[p.name] = toks
    _DOCS[key] = docs
    return docs


def body_search(store, question: str, limit: int = 3) -> list[str]:
    """Lexical search over engram bodies: no model call, no index.

    Routing answers "which topic"; this answers "which file contains these
    words". For short factual questions the second is usually the right tool.
    """
    docs = _docs(store)
    if not docs:
        return []
    df: dict[str, int] = {}
    for toks in docs.values():
        for t in toks:
            df[t] = df.get(t, 0) + 1
    n = len(docs)
    q = set(re.findall(r"[a-z0-9][a-z0-9_.\-/]{2,}", question.lower()))
    q = {t for t in q if t not in _STOP and df.get(t, n) <= max(2, n * 0.15)}
    scored = []
    for name, toks in docs.items():
        # presence of a rare word beats repetition of a common one
        score = sum(math.log(1 + n / df[t]) for t in q if t in toks)
        if score:
            scored.append((score, name))
    scored.sort(key=lambda x: -x[0])
    return [name for _, name in scored[:limit]]


def retrieve(store, question: str, max_files: int = 3):
    """Search first, route second.

    A short factual question ("which model is the sink?") names a thing, not a
    topic; the engram that contains that word is the right answer and lexical
    search finds it without a model call. The tree is the fallback for topical
    questions, where no single word decides.
    """
    names = body_search(store, question, limit=min(2, max_files))
    if names:
        return names, 0, 0
    start = smart_start(store, question)
    names, hops, stats = walk(store, question, max_files, start)
    return names, stats["calls"], stats["tokens"]


def score_routes(store, name: str, question: str) -> list[tuple[int, str]]:
    """Score a neuron's route lines by keyword overlap (no model call)."""
    p = store / name
    if not p.exists():
        return []
    words = set(re.findall(r"[a-z0-9][a-z0-9_.\-/]{2,}", question.lower()))
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = ROUTE.match(line.strip())
        if not m:
            continue
        kws = m.group("kw").split()
        score = sum(1 for k in kws if k in words or (len(k) > 3 and k in question.lower()))
        if score:
            out.append((score, m.group("t")))
    out.sort(key=lambda x: -x[0])
    return out


def children(store, name: str) -> list[str]:
    p = store / name
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    if not all(ROUTE.match(l) or EDGE.match(l) for l in lines):
        return []          # a content file, not a router
    return [m.group("t") for m in ROUTE.finditer(text)] + [m.group("target") for m in EDGE.finditer(text)]


def walk(store, question: str, max_files: int, start: list[str] | None = None):
    """Walk the tree. With `start`, the T1 selection is skipped: the caller (the
    main agent, which already has MEMORY.md in its system prompt) named the
    neuron(s), and the bare evaluator only handles T2 downward."""
    stats = {"calls": 0, "tokens": 0}
    hops = []

    def ask(system: str, body: str) -> list[str]:
        text, tok = call(system.replace("{n}", str(max_files)), body)
        stats["calls"] += 1
        stats["tokens"] += tok
        return parse_files(text)[:max_files]

    if start:
        picked = [f for f in start if (store / f).exists()][:max_files]
        hops.append(("main agent → " + ", ".join(picked), picked))
    else:
        index, _ = index_text(store)
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
        scored = score_routes(store, name, question) if LOCAL_HOPS else []
        if scored and scored[0][0] >= 2 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 2):
            top = scored[0][0]
            got = [t for s_, t in scored if s_ == top][:max_files]
            hops.append((name + " (local)", got))
        else:
            card = card_with_titles(store, name)
            got = ask(NODE_SYSTEM, f"CARD:\n{card[:7000]}\n\nQUESTION: {question}")
            hops.append((name, got))
        for child in got:
            if child not in visited and (store / child).exists():
                visited.add(child)
                frontier.append((child, tier + 1))
    return engrams[:max_files], hops, stats


SHEET_SYSTEM = (
    "You are a memory router. You get a keyword index and the routing cards of "
    "the memories that have children. Each index line is '<keywords> -> <file.md>'. "
    "Each card lists '<when condition> \u2192 <child.md>'. Follow the cards yourself "
    "and reply with JSON only: {\"files\":[\"<name>.md\", ...]} naming at most {n} "
    "ENGRAM files (files that appear as a target and have no card of their own) "
    "which contain the answer. No prose."
)


def read_for_context(store, files: list[str], question: str, per_file: int = 2500) -> str:
    """Return the engram text, trimmed to the sections that match the question.

    An engram is one subject, but a 5 KB file may still hold several aspects; the
    question usually needs one. Full text when it is short or nothing matches.
    """
    words = set(re.findall(r"[a-z0-9][a-z0-9_.\-/]{3,}", question.lower()))
    parts = []
    for name in files:
        p = store / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) <= per_file:
            parts.append(text)
            continue
        chunks, cur = [], []
        for line in text.splitlines():
            if line.startswith("## ") and cur:
                chunks.append("\n".join(cur)); cur = [line]
            else:
                cur.append(line)
        if cur:
            chunks.append("\n".join(cur))
        scored = sorted(((sum(1 for w in re.findall(r"[a-z0-9][a-z0-9_.\-/]{3,}", c.lower()) if w in words), c)
                         for c in chunks), key=lambda x: -x[0])
        keep = scored[0][1] if scored and scored[0][0] > 0 else text
        parts.append(keep[:per_file])
    return "\n\n".join(parts)


def routing_sheet(store) -> str:
    idx, cards = [], []
    for line in (store / "MEMORY.md").read_text(encoding="utf-8").splitlines():
        if "\u2192" in line and not line.lstrip().startswith("#"):
            kw, target = line.rsplit("\u2192", 1)
            if target.strip().endswith(".md"):
                idx.append(" ".join(k.strip().lstrip("!")
                                    for k in re.split(r"[,\s]+", kw) if k.strip())
                           + " \u2192 " + target.strip())
    for path in sorted(store.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        body = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
        if body and all(ROUTE.match(l) for l in body):
            cards.append("## " + path.name + "\n" + "\n".join(body))
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
    ap.add_argument("--model-index", action="store_true",
                    help="use a model call for T1 instead of the free lexical pick")
    ap.add_argument("--start", nargs="+", metavar="FILE",
                    help="neuron(s) the main agent already picked from the index; "
                         "skips the T1 router call")
    ap.add_argument("--read", action="store_true",
                    help="print the engram text, which is what the caller feeds back")
    ap.add_argument("--max-chars", type=int, default=0,
                    help="cap per file when --read is used (0 = whole file)")
    args = ap.parse_args()
    store = __import__("pathlib").Path(args.store).expanduser()
    if args.sheet:
        engrams, hops, stats = walk_sheet(store, args.question, args.max_files)
    else:
        start = args.start
        if not start and not args.model_index:
            start = smart_start(store, args.question)
        engrams, hops, stats = walk(store, args.question, args.max_files, start)
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
