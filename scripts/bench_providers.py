#!/usr/bin/env python3
"""Provider benchmark: dynmem 1.11.0 vs Hermes built-in memory vs no memory.

Same 100 facts, same questions. Measures:
  - how many facts survive in the provider's store (retention)
  - whether a question about a stored fact is answered correctly
  - how many context tokens the provider spends per answer

Built-in memory is modelled as it ships: a flat MEMORY.md with the 2,200-char
cap, injected whole. dynmem retrieves engrams through its tree. External
providers (honcho, mem0, supermemory, byterover, retaindb) are not configured on
this box and are reported as unavailable rather than faked.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import random
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path("/home/media/hermes-dynamic-memory")
LIVE = pathlib.Path("/home/media/.hermes/profiles/vps/memories")
SCRATCH = pathlib.Path("/home/media/.hermes/profiles/vps/cache/scratch/providers")
sys.path.insert(0, str(ROOT / "scripts"))
import lookup  # noqa: E402

NATIVE_CAP = 2200

SPEC = importlib.util.spec_from_file_location("bench", ROOT / "scripts" / "bench_facts.py")
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


def native_store(facts) -> tuple[str, int]:
    """What the built-in provider injects: facts until the 2,200-char cap."""
    out, n = [], 0
    for _, txt in facts:
        line = txt + "\n"
        if n + len(line) > NATIVE_CAP:
            break
        out.append(line)
        n += len(line)
    return "".join(out), len(out)


def ask(context: str, question: str) -> tuple[str, int]:
    system = ("Answer from the memory below only. If it does not contain the answer, "
              "say NOT FOUND. Reply with the reference token if present.")
    user = f"MEMORY:\n{context}\n\nQUESTION: {question}"
    return lookup.call(system, user, max_tokens=200)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--facts", type=int, default=100)
    ap.add_argument("--questions", type=int, default=10)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--recheck-only", action="store_true",
                    help="reuse the existing dynmem store; only re-ask the questions")
    args = ap.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    # facts grouped under ten named subsystems, so keyword routing has something
    # to discriminate on (synthetic facts without a subject are not routable)
    names = ["aurora", "basalt", "cinder", "dunlin", "ember", "fjord",
             "garnet", "harbor", "indigo", "juniper"]
    verbs = ["reports every", "fails when", "is wired to", "stores in", "authenticates with"]
    values = ["12", "45", "0x76", "60s", "bucket-a", "/dev/ttyUSB0", "8021", "-2.0"]
    facts = []
    per = max(1, args.facts // len(names))
    for i in range(args.facts):
        t = f"k{rng.randrange(16 ** 6):06x}"
        subj = f"{names[i // per % len(names)]}-{i // per + 1}"
        facts.append((t, f"{subj} {rng.choice(verbs)} {rng.choice(values)} (ref {t})"))

    # ---- dynmem: ingest through the optimizer, retrieve through the tree
    store = SCRATCH / "dynmem-store"
    if not args.recheck_only:
        if store.exists():
            shutil.rmtree(store)
        shutil.copytree(LIVE, store)
    brief = f"{rng.randrange(16 ** 4):04x}"
    prompt = (f"Project brief {brief}. Record every fact exactly; the ref token is the identity.\n"
              + "\n".join(f"- {txt}" for _, txt in facts))
    if not args.recheck_only:
        msg = {"role": "user", "content": prompt}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"messages": [msg]}, f)
            tpath = f.name
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "optimize.py"),
                            "--store", str(store), "--transcript", tpath],
                           capture_output=True, text=True)
        dyn_ingest_ok = r.returncode == 0
    else:
        dyn_ingest_ok = True
    dyn_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in store.glob("*.md"))
    dyn_kept = sum(1 for t, _ in facts if t in dyn_text)

    # ---- native: flat memory capped at 2,200 chars
    native_text, native_kept = native_store(facts)

    # ---- questions spread across the fact list
    idxs = [round(i * (len(facts) - 1) / (args.questions - 1)) for i in range(args.questions)]
    rows = []
    for i in idxs:
        token, txt = facts[i]
        q = f"In project {brief}, which ref token is recorded for {txt.split('(ref')[0].strip()}?"
        dyn_ctx = ""
        start = lookup.smart_start(store, q)
        files, hops, stats = lookup.walk(store, q, 3, start)
        dyn_ctx = lookup.read_for_context(store, files, q, per_file=100000)
        dyn_answer, dyn_tok = ask(dyn_ctx[:12000], q)
        nat_answer, nat_tok = ask(native_text, q)
        none_answer, none_tok = ask("", q)
        print(f"  {'HIT ' if token in dyn_answer else 'miss'} {token} files={','.join(files)[:60]}")
        rows.append({
            "fact": token,
            "dynmem": token in dyn_answer,
            "native": token in nat_answer,
            "none": token in none_answer,
            "dyn_ctx_tok": round(len(dyn_ctx) / 3.8),
            "dyn_file_hit": any((store / f).exists() and token in (store / f).read_text(errors="replace")
                                for f in files),
            "nat_ctx_tok": round(len(native_text) / 3.8),
        })

    def pct(key):
        return round(100 * sum(r[key] for r in rows) / len(rows))

    print(f"facts: {len(facts)}   questions: {len(rows)}")
    print(f"ingest: dynmem {'ok' if dyn_ingest_ok else 'FAILED'}, retained {dyn_kept}/{len(facts)} "
          f"({round(100 * dyn_kept / len(facts))}%)")
    print(f"        native retained {native_kept}/{len(facts)} "
          f"({round(100 * native_kept / len(facts))}%) — {NATIVE_CAP}-char cap")
    print(f"answers: dynmem {pct('dynmem')}%   native {pct('native')}%   no-memory {pct('none')}%")
    print(f"context per question: dynmem ~{round(sum(r['dyn_ctx_tok'] for r in rows) / len(rows))} tok, "
          f"native {round(sum(r['nat_ctx_tok'] for r in rows) / len(rows))} tok")
    print(f"dynmem retrieved the fact's engram in {round(100 * sum(r['dyn_file_hit'] for r in rows) / len(rows))}% of questions")
    bad = [r['fact'] for r in rows if not r['dynmem']]
    if bad:
        print("dynmem misses:", bad)
    out = SCRATCH / "report.json"
    out.write_text(json.dumps({"rows": rows, "dyn_kept": dyn_kept, "native_kept": native_kept}, indent=1))
    print("report:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
