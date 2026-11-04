#!/usr/bin/env python3
# bench_pushback — does a "no, I meant X" that is NOT a memory error produce a demotion?
#
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory.
#
# The dangerous failure for memcheck is not a missed correction, it is a false
# one: the user refines or pushes back, the model dutifully reports
# verdict=wrong, and a perfectly good keyword gets demoted. So this bench feeds
# six pushbacks that are NOT memory errors (detail, time, arithmetic, abandoned
# topic, which-item) plus two that are, and asks the production question:
# does anything reach the demote channel?
#
#   python3 benchmarks/scripts/bench_pushback.py --runs 2
#
# Key from OPENCODE_GO_API_KEY in the process environment.

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BASE_URL = os.environ.get("BENCH_BASE_URL", "https://opencode.ai/zen/go/v1")
MODEL = os.environ.get("BENCH_MODEL", "deepseek-v4.1-flash")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "plugin" / "memory-shaper"))
import memcheck  # noqa: E402

INDEX = """# Memory Index — keyword,keyword,keyword → file.md

keyword,keyword,keyword → file.md
hermes,gateway,telegram,systemd,unit → daemon-unit.md
aklima,klima,connectlife,hisense,svrake → aklima-app.md
backup,rsync,pi,offsite,optiplex → backup-job.md
tv,tcl,ekupi,warranty,serial → tv-purchase.md
gold,zlato,grams,debt,kids → gold-ledger.md
x,twitter,ockentap,session,cookies → x-account.md
"""

BODIES = {
    "daemon-unit.md": ("The daemon unit runs as a systemd service. Restarting it from "
                       "inside its own process is refused; use the shell helper instead. "
                       "The telegram bridge attaches to the same unit."),
    "aklima-app.md": ("aKlima talks to the Hisense AC through ConnectLife. The svrake "
                      "window is the cheap tariff block, 22:00 to 06:00."),
    "backup-job.md": ("The offsite copy is an rsync run from the optiplex to the pi every "
                      "night at 02:00. A failed leg logs exit 24 and retries once."),
    "tv-purchase.md": ("The TCL 55C6K was bought at ekupi with a five year warranty. The "
                       "serial is on the box; registration extends the guarantee."),
    "gold-ledger.md": ("Grams of 24K held for the kids. Each gift is recorded in grams, "
                       "not in BAM, so the total is a weight."),
    "x-account.md": ("The ockentap session lives in a cloakbrowser profile on port 9222; "
                     "cookies survive a reboot because it runs under systemd."),
}

# (id, turn-1 prompt, turn-1 answer, pushback, kind, expected-wrong-file)
CASES = [
    (1, "how do I restart the daemon unit?", "Use the shell helper from outside the process.",
     "no, I wasn't talking about that - I meant the one on the pi box", "not-an-error", None),
    (2, "when does the backup run?", "02:00 nightly, rsync from the optiplex to the pi.",
     "no, I meant the one from last Tuesday", "not-an-error", None),
    (3, "which TV did I buy?", "The TCL 55C6K from ekupi.",
     "no, I wasn't asking about that - I meant when the warranty runs out", "not-an-error", None),
    (4, "what is the gold total?", "The ledger says 84 grams.",
     "no, that's not right, you added it up wrong", "not-an-error", None),
    (5, "how do I restart the daemon unit?", "Use the shell helper from outside the process.",
     "no, forget it - what is the weather tomorrow", "not-an-error", None),
    (6, "how do I restart the daemon unit?", "Use the shell helper from outside the process.",
     "no, I meant the one that copies things at night", "not-an-error", None),
    # Controls: these ARE memory misses and must still fire.
    (7, "how do I restart the daemon unit?", "Use the shell helper from outside the process.",
     "no, that's not it - I meant the backup job", "memory-error", "daemon-unit.md"),
    (8, "when does the warranty expire on the TV?", "Five years from purchase, per the TCL note.",
     "no, I meant the gold ledger, not the TV", "memory-error", "tv-purchase.md"),
]


def call(system: str, user: str, session: str) -> str:
    import urllib.request

    key = os.environ.get("OPENCODE_GO_API_KEY") or os.environ.get("BENCH_API_KEY")
    if not key:
        raise SystemExit("OPENCODE_GO_API_KEY not set")
    body = {"model": MODEL,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": 1200}
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}",
                 "User-Agent": "hermes-agent/bench",
                 "x-opencode-session": session})
    with urllib.request.urlopen(req, timeout=240) as fh:
        return json.loads(fh.read().decode())["choices"][0]["message"]["content"]


def run(runs: int) -> dict:
    entries = memcheck.parse_index(INDEX)
    records = []
    for run_no in range(1, runs + 1):
        for cid, prompt, answer, pushback, kind, _expected in CASES:
            user = (f"Turn 1 user: {prompt}\n"
                    f"Turn 1 assistant: {answer}\n"
                    f"Turn 2 user: {pushback}\n\n{memcheck.T2_TEMPLATE}")
            raw = None
            for attempt in (1, 2):
                try:
                    raw = call(INDEX, user, f"bench-pushback-{run_no}-{cid}-{attempt}")
                except Exception as exc:
                    raw = None
                if raw:
                    break
            if not raw:
                records.append({"id": cid, "kind": kind, "error": "empty reply"})
                continue
            visible, raw_tag, misplaced = memcheck.split_tag(raw)
            s = memcheck.parse_tag(raw_tag or "")
            s["used_files"] = []
            problems = memcheck.validate(s, entries, BODIES, [prompt, pushback])
            if misplaced:
                problems.append("text_after_tag")
            s["hook_shared"] = memcheck.hook_shared(
                s.get("hook"), memcheck.split_targets(s.get("wrong")),
                memcheck.split_targets(s.get("right")), entries, [prompt, pushback])
            rec = {"id": cid, "kind": kind, "run": run_no,
                   "tag_present": bool(raw_tag),
                   "verdict": s.get("verdict"), "wrong": s.get("wrong"),
                   "right": s.get("right"), "hook": s.get("hook"),
                   "hook_shared": s["hook_shared"],
                   "problems": problems, "leaked": "<mc" in visible,
                   "terms": memcheck.prompt_terms(pushback, entries,
                                                  target=memcheck.split_targets(s.get("right"))[0]
                                                  if s.get("right") else None)}
            rec["t"] = s.get("t")
            records.append(rec)
    return {"records": records}


def summarise(recs: list[dict]) -> str:
    ok = [r for r in recs if not r.get("error")]
    lines = [f"replies: {len(ok)}/{len(recs)}  tag present: {sum(r['tag_present'] for r in ok)}"]
    for kind in ("not-an-error", "memory-error"):
        rows = [r for r in ok if r["kind"] == kind]
        wrong = [r for r in rows if r["verdict"] == "wrong"]
        lines.append(f"{kind:12s} n={len(rows)}  verdict=wrong {len(wrong)}  "
                     f"problems {sum(1 for r in rows if r['problems'])}")
        for r in rows:
            flag = "FALSE POSITIVE" if kind == "not-an-error" and r["verdict"] == "wrong" else ""
            lines.append(f"  id={r['id']} verdict={r['verdict']!s:7s} wrong={r['wrong']!s:18s} "
                         f"right={r['right']!s:18s} hook={r['hook']!s:10s} "
                         f"shared={r['hook_shared']} probs={r['problems']} {flag}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2)
    args = ap.parse_args(argv)

    data = run(args.runs)
    print(summarise(data["records"]))

    # Feed the records through the production scorer: what would the index do?
    scored = memcheck.score([r for r in data["records"] if not r.get("error")])
    print("\nscore(): review", scored.get("review") or "{}", "| promote",
          {k: v for k, v in scored["promote"].items()} or "{}",
          "| collisions", scored["ambiguous_hooks"] or "{}")

    out = REPO / "benchmarks" / "results" / "memcheck-pushback"
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out / f"{stamp}.json").write_text(json.dumps(
        {"model": MODEL, "data": data, "scored": scored}, indent=2), encoding="utf-8")
    print("saved", out / f"{stamp}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
