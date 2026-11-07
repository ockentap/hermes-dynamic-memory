#!/usr/bin/env python3
"""Memory evaluator: a bare, stateless router call.

System prompt is ONLY the memory-evaluation instruction — no persona, no skills,
no workspace rules, no memory injection. The caller passes one hub file; the
evaluator follows its `when` edges to a leaf and returns the path (optionally a
short answer read from that leaf).

    python3 evalmem.py --hub layouts/d2/medivia-open-server.md \
        --question "What is the reward for the elven sword quest?" --answer

Model defaults to the session model; override with --model / --base-url.
The key is read from $OPENAI_API_KEY (or --api-key-env).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

SYSTEM = (
    "You are a memory evaluator. You are given one memory hub file and a user "
    "question. Choose the single child file whose 'when' condition best matches "
    "the question. Reply with JSON only: {\"file\":\"<name>.md\"}. If no child "
    "matches, reply {\"file\":null}. Do not explain."
)
ANSWER_SYSTEM = (
    "You are a memory evaluator. Answer the user's question using only the "
    "memory file below. Quote the exact line that supports the answer, then give "
    "a one-sentence answer. If the file does not contain the answer, say NOT FOUND."
)
EDGE = re.compile(r"^[-*]\s+when\s+(?P<cond>.+?)\s+(?:\u2192|->)\s+(?P<target>[A-Za-z0-9_.\-]+\.md)\s*$", re.M)


def call(base, key, model, system, user, max_tokens=512):
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                base.rstrip("/") + "/chat/completions",
                data=json.dumps({"model": model, "temperature": 0,
                                 "max_tokens": max_tokens,
                                 "messages": [{"role": "system", "content": system},
                                              {"role": "user", "content": user}]}).encode(),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                         "x-opencode-session": "memeval-" + os.urandom(4).hex(),
                         "User-Agent": "dynmem-memeval/1.0"},
            )
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.load(r)
            ch = d["choices"][0]
            if ch.get("finish_reason") == "length" and max_tokens < 2048:
                return call(base, key, model, system, user, 2048)
            return ch["message"].get("content") or "", d.get("usage") or {}
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode()[:200]}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(last)


def load_key(name: str) -> str:
    for n in (name, "OPENAI_API_KEY", "OPENCODE_GO_API_KEY"):
        v = os.environ.get(n, "")
        if v:
            return v
    p = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8", errors="ignore"):
            m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*)", line)
            if m and m.group(1) in ("OPENCODE_GO_API_KEY", "OPENAI_API_KEY"):
                return m.group(2).strip().strip('"').strip("'")
    return ""


def parse(text):
    m = re.search(r"\{.*?\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0)).get("file")
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", required=True)
    ap.add_argument("--question", required=True)
    ap.add_argument("--model", default=os.environ.get("MEMEVAL_MODEL", "deepseek-v4.1-flash"))
    ap.add_argument("--base-url", default=os.environ.get("MEMEVAL_BASE_URL", "https://opencode.ai/zen/go/v1"))
    ap.add_argument("--api-key-env", default="OPENAI_API_KEY")
    ap.add_argument("--max-hops", type=int, default=6)
    ap.add_argument("--answer", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    key = load_key(args.api_key_env)
    if not key:
        raise SystemExit(f"set ${args.api_key_env} (or OPENCODE_GO_API_KEY in ~/.hermes/.env)")

    path = args.hub
    hops, tokens = [], 0
    for _ in range(args.max_hops + 1):
        text = open(path, encoding="utf-8", errors="replace").read()
        edges = {m.group("target") for m in EDGE.finditer(text)}
        if not edges:
            break
        content, usage = call(args.base_url, key, args.model, SYSTEM,
                              "QUESTION:\n" + args.question + "\n\nHUB:\n" + text)
        tokens += usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
        target = parse(content)
        hops.append({"hub": os.path.basename(path), "chose": target})
        if not target or target not in edges:
            break
        path = os.path.join(os.path.dirname(path), target)
        if not os.path.exists(path):
            break

    result = {"final": os.path.basename(path), "path": path, "hops": hops, "router_tokens": tokens}
    if args.answer and os.path.exists(path):
        leaf = open(path, encoding="utf-8", errors="replace").read()
        ans, usage = call(args.base_url, key, args.model, ANSWER_SYSTEM,
                          "QUESTION:\n" + args.question + "\n\nFILE:\n" + leaf, max_tokens=400)
        result["answer_tokens"] = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
        result["answer"] = ans.strip()
        result["total_tokens"] = tokens + result["answer_tokens"]
    if args.json:
        print(json.dumps(result))
    else:
        print(f'final: {result["final"]}  hops: {len(hops)}  tokens: {result.get("total_tokens", tokens)}')
        if "answer" in result:
            print(result["answer"])


if __name__ == "__main__":
    main()
