"""memlook — the dynmem lookup pipeline.

First user turn: a bare evaluator gets the index and the user's message, names
the memories that matter, and every neuron it names gets another bare call with
its routing card until the picks are engrams. Their text is injected into that
first turn. Later turns get the tool `memory_lookup(question)` instead.

Bare means: the only system prompt is the router instruction. No persona, no
tools, no memory injection.
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.request
from pathlib import Path

BASE = os.environ.get("MEMLOOK_BASE_URL", "https://opencode.ai/zen/go/v1")
MODEL = os.environ.get("MEMLOOK_MODEL", "deepseek-v4.1-flash")
MAX_TIER = 5          # index -> 3 neurons -> engram
MAX_FILES = 3         # per hop
CONTEXT_BUDGET = 12000  # characters injected into the first turn
TIMEOUT = 25          # seconds; the hook budget is 30

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
TRIVIAL = re.compile(r"^(yes|no|ok|okay|sure|thanks|thank you|y|n|yep|nope|yeah|nah|hi|hey|"
                     r"hello|yo|continue|go ahead|do it|proceed|got it|cool|nice|great|done|next|lgtm|k)"
                     r"[\s!?.:;,\"'\u2014\u2013\u2026]*$", re.I)

_cache: dict[str, str] = {}
_lock = threading.Lock()


def _home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def _store() -> Path:
    return _home() / "memories"


def _key() -> str:
    for n in ("OPENCODE_GO_API_KEY", "OPENAI_API_KEY"):
        if os.environ.get(n):
            return os.environ[n]
    for p in (_home() / ".env", Path(os.path.expanduser("~/.hermes/.env"))):
        try:
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*)", line)
                if m and m.group(1) in ("OPENCODE_GO_API_KEY", "OPENAI_API_KEY"):
                    return m.group(2).strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def _call(system: str, user: str, max_tokens: int = 1200) -> str:
    key = _key()
    if not key:
        return ""
    body = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
            "reasoning_effort": "none",
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}
    req = urllib.request.Request(
        BASE.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "x-opencode-session": "memlook-" + os.urandom(4).hex(),
                 "User-Agent": "dynmem-memlook/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    ch = d["choices"][0]
    text = ch["message"].get("content") or ""
    if not text and ch.get("finish_reason") == "length" and max_tokens < 3000:
        return _call(system, user, 3000)
    return text


def _files(text: str) -> list[str]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    out = data.get("files") or []
    if isinstance(out, str):
        out = [out]
    return [f for f in out if isinstance(f, str) and f.endswith(".md")]


def index_text(store: Path) -> str:
    """Compact router view: 'target: kw kw kw' (no commas/arrows: fewer tokens)."""
    lines = []
    for line in (store / "MEMORY.md").read_text(encoding="utf-8").splitlines():
        if "\u2192" not in line or line.lstrip().startswith("#"):
            continue
        kw, target = line.rsplit("\u2192", 1)
        if not target.strip().endswith(".md"):
            continue
        kws = " ".join(k.strip().lstrip("!") for k in re.split(r"[,\s]+", kw.strip()) if k.strip())
        lines.append(kws + " \u2192 " + target.strip())
    return "\n".join(lines)


ROUTE = re.compile(r"^(?P<kw>.+?)\s*(?:\u2192|->)\s*(?P<t>[A-Za-z0-9_.\-]+\.md)\s*$", re.M)


def children(store: Path, name: str) -> list[str]:
    p = store / name
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    if not all(ROUTE.match(l) or EDGE.match(l) for l in lines):
        return []
    return [m.group("t") for m in ROUTE.finditer(text)] + [m.group("target") for m in EDGE.finditer(text)]


def lexical_pick(store: Path, question: str, limit: int = 2) -> list[str]:
    """T1 for free: score index lines by keyword overlap, no model call.

    The main agent already carries MEMORY.md in its system prompt, so paying a
    router call to re-read the index is waste. This is the local approximation;
    the agent can override it by naming a file explicitly.
    """
    words = set(re.findall(r"[a-z0-9][a-z0-9_.\-/]{2,}", question.lower()))
    scored = []
    for line in (store / "MEMORY.md").read_text(encoding="utf-8", errors="replace").splitlines():
        if "\u2192" not in line or line.lstrip().startswith("#"):
            continue
        kw, target = line.rsplit("\u2192", 1)
        target = target.strip()
        if not target.endswith(".md"):
            continue
        kws = [k.strip().lstrip("!") for k in re.split(r"[,\s]+", kw) if k.strip()]
        score = sum(1 for k in kws if k in words or (len(k) > 3 and k in question.lower()))
        if score:
            scored.append((score, target))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return []
    top = scored[0][0]
    return [t for score, t in scored if score == top][:limit]


def walk(question: str, start: list[str] | None = None) -> dict:
    store = _store()
    stats = {"calls": 0, "tokens": 0}
    hops = []

    def ask(system: str, body: str) -> list[str]:
        text = _call(system.replace("{n}", str(MAX_FILES)), body)
        stats["calls"] += 1
        return _files(text)[:MAX_FILES]

    picked = start or lexical_pick(store, question)
    hops.append(("main agent", picked))
    queue = [(f, 2) for f in picked]
    seen, engrams = set(picked), []
    while queue:
        name, tier = queue.pop(0)
        kids = children(store, name)
        if not kids or tier >= MAX_TIER:
            engrams.append(name)
            continue
        try:
            card = (store / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        got = ask(NODE_SYSTEM, f"CARD:\n{card[:6000]}\n\nQUESTION: {question}")
        hops.append((name, got))
        for child in got:
            if child not in seen and (store / child).exists():
                seen.add(child)
                queue.append((child, tier + 1))
    return {"files": engrams, "hops": hops, "calls": stats["calls"]}


def context_for(files: list[str], budget: int = CONTEXT_BUDGET) -> str:
    store = _store()
    parts, used = [], 0
    for name in files:
        try:
            text = (store / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if used + len(text) > budget:
            text = text[: max(0, budget - used)] + "\n[... truncated; read the file for the rest]"
        parts.append(f"### memory: {name}\n{text}")
        used += len(text)
        if used >= budget:
            break
    return "\n\n".join(parts)


def _bounded(fn, seconds: int):
    box = {}

    def run():
        try:
            box["value"] = fn()
        except Exception as exc:  # never break the turn
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    return box.get("value")


def _hook(session_id: str = "", user_message: str = "", is_first_turn: bool = False,
          platform: str = "", **_kw):
    """pre_llm_call: on the first substantive user turn, inject the engrams."""
    if not is_first_turn:
        return None
    if (platform or "").lower() in {"cron", "subagent", "oneshot", "batch"}:
        return None
    q = (user_message or "").strip()
    if len(q) < 12 or q.startswith("/") or TRIVIAL.match(q):
        return None
    key = session_id or "default"
    with _lock:
        if key in _cache:
            return {"context": _cache[key]}
    res = _bounded(lambda: walk(q), TIMEOUT)
    if not res or not res.get("files"):
        return None
    text = context_for(res["files"])
    if not text:
        return None
    block = f"## Memory lookup (automatic, tier walk)\nfiles: {', '.join(res['files'])}\n\n{text}"
    with _lock:
        _cache[key] = block
    return {"context": block}


SCHEMA = {
    "name": "memory_lookup",
    "description": ("Find the memory files relevant to a question by walking the dynmem tree with "
                    "bare evaluators (index -> neurons -> engrams) and return their text. Use it "
                    "whenever you need to remember something mid-conversation."),
    "parameters": {"type": "object",
                   "properties": {"question": {"type": "string",
                                               "description": "What you are trying to remember, phrased as a question"}},
                   "required": ["question"]},
}


def _tool(question: str = "", start: str = "", **_kw) -> str:
    if not (question or "").strip():
        return json.dumps({"error": "question is required"})
    start_list = [s.strip() for s in re.split(r"[,\s]+", start) if s.strip()] or None
    res = walk(question, start_list)
    return json.dumps({"files": res["files"], "hops": res["hops"], "calls": res["calls"],
                       "context": context_for(res["files"])})


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", _hook)
    ctx.register_tool("memory_lookup", "memory", SCHEMA, _tool,
                      description=SCHEMA["description"], emoji="\U0001F9E0")
