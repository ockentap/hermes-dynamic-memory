#!/usr/bin/env python3
"""Fact-retention harness for dynmem.

Two modes, both measuring the SAME thing: of 100 facts given to the system, how
many survive verbatim in the engrams afterwards.

  complex : 5 prompts x 100 facts in one message, one optimisation pass each
  long    : 5 sessions x 20 messages, 100 facts spread randomly, the optimiser
            fired after every message (what the 15-minute hook does)

A fact is a unique token (e.g. `qz7x4`) embedded in a sentence, so retention is
exact substring presence anywhere in the store.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path("/home/media/hermes-dynamic-memory")
OPT = ROOT / "scripts" / "optimize.py"
LIVE = pathlib.Path("/home/media/.hermes/profiles/vps/memories")
SCRATCH = pathlib.Path("/home/media/.hermes/profiles/vps/cache/scratch/facts")

SUBJECTS = [
    "pump controller", "greenhouse logger", "solar tracker", "water softener",
    "garage door", "well pump", "boiler loop", "irrigation valve", "heat pump",
]

VERBS = [
    "reports every", "fails when", "is wired to GPIO", "stores in bucket",
    "authenticates with token", "is calibrated at", "timeouts after", "logs to",
]


def token() -> str:
    return "k" + secrets.token_hex(3)


def make_facts(n: int, rng: random.Random):
    facts = []
    for i in range(n):
        t = token()
        subject = rng.choice(SUBJECTS)
        kind = rng.choice(VERBS)
        value = rng.choice(["12", "45", "0x76", "60s", "bucket-a", "/dev/ttyUSB0", "8021", "-2.0"])
        facts.append((t, f"{subject} {kind} {value} (ref {t})"))
    return facts


def build_prompt(facts) -> str:
    lines = [f"Project brief {secrets.token_hex(2)}. Record every fact exactly; the ref token is the identity."]
    lines += [f"- {txt}" for _, txt in facts]
    return "\n".join(lines)


def store_for(name: str) -> pathlib.Path:
    d = SCRATCH / name
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(LIVE, d)
    return d


def run_optimize(store: pathlib.Path, messages: list[dict], label: str) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"messages": messages}, f)
        path = f.name
    t0 = time.time()
    r = subprocess.run([sys.executable, str(OPT), "--store", str(store), "--transcript", path],
                       capture_output=True, text=True, timeout=900)
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"\((\d+) tokens\)", out)
    return {"ok": r.returncode == 0, "tokens": int(m.group(1)) if m else 0,
            "seconds": round(time.time() - t0, 1), "out": out.strip().splitlines()[-1:]}


def retention(store: pathlib.Path, facts) -> tuple[int, list[str]]:
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in store.glob("*.md"))
    missing = [t for t, _ in facts if t not in text]
    return len(facts) - len(missing), missing


def store_stats(store: pathlib.Path, before: tuple[int, int]) -> dict:
    files = [p for p in store.glob("*.md") if p.name not in {"MEMORY.md", "USER.md"}]
    n, b = len(files), sum(p.stat().st_size for p in files)
    return {"files": n - before[0], "bytes": b - before[1],
            "index_lines": sum(1 for l in (store / "MEMORY.md").read_text().splitlines() if "→" in l)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["complex", "long"], required=True)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--facts", type=int, default=100)
    ap.add_argument("--messages", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    tag = args.tag or time.strftime("%H%M%S")
    report = []

    for run in range(1, args.runs + 1):
        rng = random.Random(args.seed + run)
        facts = make_facts(args.facts, rng)
        store = store_for(f"{args.mode}-{tag}-{run}")
        base_files = [p for p in store.glob("*.md") if p.name not in {"MEMORY.md", "USER.md"}]
        before = (len(base_files), sum(p.stat().st_size for p in base_files))

        if args.mode == "complex":
            msg = {"role": "user", "content": build_prompt(facts)}
            res = run_optimize(store, [msg], f"complex-{run}")
        else:
            per = args.facts // args.messages
            buckets = [facts[i * per:(i + 1) * per] for i in range(args.messages)]
            rng.shuffle(buckets)
            res_list = []
            for i, bucket in enumerate(buckets, 1):
                msg = {"role": "user", "content": build_prompt(bucket)}
                res_list.append(run_optimize(store, [msg], f"long-{run}-{i}"))
            res = {"ok": all(r["ok"] for r in res_list),
                   "tokens": sum(r["tokens"] for r in res_list),
                   "seconds": round(sum(r["seconds"] for r in res_list), 1)}

        kept, missing = retention(store, facts)
        stats = store_stats(store, before)
        row = {"run": run, "kept": kept, "of": len(facts), "pct": round(100 * kept / len(facts)),
               "missing": missing[:8], "tokens": res["tokens"], "seconds": res["seconds"],
               "ok": res["ok"], **stats}
        report.append(row)
        print(f"run {run}: {kept}/{len(facts)} facts ({row['pct']}%)  "
              f"+{stats['files']} files  +{stats['bytes'] // 1024}KB  "
              f"index {stats['index_lines']} lines  {res['tokens']}t  {res['seconds']}s")

    out = SCRATCH / f"report-{args.mode}-{tag}.json"
    out.write_text(json.dumps(report, indent=1))
    avg = sum(r["pct"] for r in report) / len(report)
    print(f"\n{args.mode}: mean retention {avg:.1f}%  tokens {sum(r['tokens'] for r in report)}  "
          f"report {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
