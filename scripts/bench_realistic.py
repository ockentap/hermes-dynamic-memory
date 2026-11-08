#!/usr/bin/env python3
"""Realistic provider test: dynmem vs Hermes built-in memory.

Five everyday subjects, twenty facts each, written the way a person talks about
them (appliances, bike parts, network gear, irrigation zones, espresso gear).
No "ref token" scaffolding, no artificial reasoning limits: the answering calls
use the model's default reasoning.

Measured per provider:
  - facts retained in the store
  - answers correct (the model, given the provider's context, names the code)
  - requests made (ingest + query)
  - total tokens and tokens per question
  - context tokens the provider spends per question
"""
from __future__ import annotations

import argparse
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
SCRATCH = pathlib.Path("/home/media/.hermes/profiles/vps/cache/scratch/realistic")
sys.path.insert(0, str(ROOT / "scripts"))
import lookup  # noqa: E402

NATIVE_CAP = 2200

DOMAINS = {
    "kitchen remodel": {
        "items": ["fridge", "oven", "cooktop", "hood", "dishwasher", "sink", "faucet",
                  "boiling tap", "microwave", "freezer", "wine cooler", "coffee corner",
                  "pantry shelving", "backsplash tile", "floor tiles", "cabinet fronts",
                  "worktop", "under-cabinet lighting", "extractor duct", "water filter"],
        "brand": ["Bosch", "Siemens", "Miele", "AEG", "Franke", "Bora"],
        "code": "KGN-{}",
        "ask": "Which model is the {item}?",
    },
    "bike maintenance": {
        "items": ["rear derailleur", "front derailleur", "cassette", "chain", "crankset",
                  "bottom bracket", "brake pads", "rotors", "shifters", "wheelset",
                  "tyres", "tubes", "saddle", "seatpost", "handlebar", "stem",
                  "headset", "rear shock", "fork", "dropper post"],
        "brand": ["Shimano", "SRAM", "DT Swiss", "Continental", "Fox", "Race Face"],
        "code": "XT-{}",
        "ask": "Which part number is the {item}?",
    },
    "home network": {
        "items": ["main router", "garage AP", "office switch", "NAS", "UPS", "patch panel",
                  "modem", "living-room AP", "camera bridge", "printer", "Raspberry Pi",
                  "media box", "doorbell", "thermostat", "solar bridge", "test laptop",
                  "spare switch", "PoE injector", "fibre ONT", "guest AP"],
        "brand": ["MikroTik", "Ubiquiti", "TP-Link", "Netgear", "Zyxel"],
        "code": "NW-{}",
        "ask": "Which device model is the {item}?",
    },
    "garden irrigation": {
        "items": ["zone 1 lawn", "zone 2 beds", "zone 3 hedge", "zone 4 greenhouse",
                  "main valve", "pressure reducer", "filter", "controller", "rain sensor",
                  "drip line", "sprinkler head A", "sprinkler head B", "pump relay",
                  "flow meter", "moisture probe", "solenoid 1", "solenoid 2",
                  "solenoid 3", "expansion tank", "check valve"],
        "brand": ["Hunter", "Rain Bird", "Gardena", "Netafim", "Grundfos"],
        "code": "IR-{}",
        "ask": "Which model is the {item}?",
    },
    "espresso setup": {
        "items": ["grinder", "machine", "portafilter", "basket", "tamper", "distribution tool",
                  "scale", "kettle", "water filter", "drip tray", "steam tip", "group gasket",
                  "shower screen", "pressure gauge", "PID controller", "boiler", "pump",
                  "OPV spring", "milk pitcher", "knock box"],
        "brand": ["Eureka", "Lelit", "Profitec", "Baratza", "ECM"],
        "code": "ES-{}",
        "ask": "Which model is the {item}?",
    },
}


def build_dataset() -> tuple[list[dict], dict]:
    """Return (facts, briefs). Each fact: domain, item, code, sentence, question."""
    facts, briefs = [], {}
    n = 1
    for domain, spec in DOMAINS.items():
        sentences = []
        for i, item in enumerate(spec["items"], 1):
            code = spec["code"].format(f"{1000 + n}")
            brand = spec["brand"][i % len(spec["brand"])]
            month = (i % 12) + 1
            sentence = f"The {item} is a {brand} {code}, fitted on 2025-{month:02d}-{(i % 27) + 1:02d}."
            facts.append({"domain": domain, "item": item, "code": code,
                          "sentence": sentence, "question": spec["ask"].format(item=item)})
            sentences.append(sentence)
            n += 1
        paras = [" ".join(sentences[i:i + 7]) for i in range(0, len(sentences), 7)]
        briefs[domain] = "\n\n".join(paras)
    return facts, briefs


def native_store(facts) -> tuple[str, int]:
    out, total = [], 0
    for f in facts:
        line = f["sentence"] + "\n"
        if total + len(line) > NATIVE_CAP:
            break
        out.append(line)
        total += len(line)
    return "".join(out), len(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domains", type=int, default=5)
    ap.add_argument("--questions", type=int, default=20)
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    facts, briefs = build_dataset()
    domains = list(briefs)[:args.domains]
    facts = [f for f in facts if f["domain"] in domains]
    rng = random.Random(args.seed)

    store = SCRATCH / "dynmem-store"
    if store.exists():
        shutil.rmtree(store)
    shutil.copytree(LIVE, store)

    # ---- ingest: dynmem through the optimizer, one brief per domain
    lookup.CALLS = 0
    tok_before = None
    ingest_tokens = ingest_calls = 0
    for d in domains:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"messages": [{"role": "user", "content": f"Notes on the {d}:\n\n{briefs[d]}"}]}, f)
            path = f.name
        before = lookup.CALLS
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "optimize.py"),
                            "--store", str(store), "--transcript", path],
                           capture_output=True, text=True)
        # tokens are printed by optimize only when not quiet; count calls via the child is
        # not visible here, so estimate from the report line when present
        m = re.search(r"\((\d+) tokens\)", r.stdout)
        ingest_tokens += int(m.group(1)) if m else 0
        ingest_calls += max(1, len(re.findall(r"🧠", r.stdout)))
        print(f"  ingested {d}: exit {r.returncode}")

    dyn_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in store.glob("*.md"))
    dyn_kept = sum(1 for f in facts if f["code"] in dyn_text)
    native_text, native_kept = native_store(facts)

    # ---- questions, evenly spread
    step = max(1, len(facts) // args.questions)
    sample = facts[::step][:args.questions]

    rows = []
    for f in sample:
        q = f["question"]
        start = lookup.smart_start(store, q)
        files, calls, rtok = lookup.retrieve(store, q, 3)
        stats = {"calls": calls, "tokens": rtok}
        ctx = lookup.read_for_context(store, files, q, per_file=100000)
        dyn_ans, dyn_tok = lookup.call(
            "Answer from the memory below only. If it is not there, say NOT FOUND.",
            f"MEMORY:\n{ctx}\n\nQUESTION: {q}", max_tokens=400, reasoning=None)
        found = lookup.body_search(store, q, limit=2)
        ctx_s = "\n\n".join((store / f).read_text(encoding="utf-8", errors="replace")
                             for f in found if (store / f).exists())
        sea_ans, sea_tok = lookup.call(
            "Answer from the memory below only. If it is not there, say NOT FOUND.",
            f"MEMORY:\n{ctx_s}\n\nQUESTION: {q}", max_tokens=400, reasoning=None)
        nat_ans, nat_tok = lookup.call(
            "Answer from the memory below only. If it is not there, say NOT FOUND.",
            f"MEMORY:\n{native_text}\n\nQUESTION: {q}", max_tokens=400, reasoning=None)
        rows.append({"q": q, "code": f["code"],
                     "dyn": f["code"] in dyn_ans, "nat": f["code"] in nat_ans,
                     "sea": f["code"] in sea_ans, "sea_tok": sea_tok,
                     "sea_files": found,
                     "dyn_calls": stats["calls"] + 1, "dyn_tok": stats["tokens"] + dyn_tok,
                     "nat_calls": 1, "nat_tok": nat_tok,
                     "dyn_ctx": round(len(ctx) / 3.8), "nat_ctx": round(len(native_text) / 3.8)})

    def pct(key):
        return round(100 * sum(r[key] for r in rows) / len(rows))

    dyn_q_tok = sum(r["dyn_tok"] for r in rows)
    nat_q_tok = sum(r["nat_tok"] for r in rows)
    print(f"\ndomains: {len(domains)}  facts: {len(facts)}  questions: {len(rows)}")
    print(f"retained: dynmem {dyn_kept}/{len(facts)}, native {native_kept}/{len(facts)}")
    print(f"answers:  dynmem-tree {pct('dyn')}%   dynmem-search {pct('sea')}%   native {pct('nat')}%")
    print(f"requests: dynmem {sum(r['dyn_calls'] for r in rows)} query "
          f"(+{ingest_calls} ingest)   native {sum(r['nat_calls'] for r in rows)} query")
    print(f"tokens:   dynmem {dyn_q_tok + ingest_tokens} total ({dyn_q_tok} query, "
          f"{ingest_tokens} ingest)   native {nat_q_tok} total")
    print(f"per question: dynmem-tree {round(dyn_q_tok / len(rows))} tok, "
          f"dynmem-search {round(sum(r['sea_tok'] for r in rows) / len(rows))} tok, "
          f"native {round(nat_q_tok / len(rows))} tok")
    print(f"context:  dynmem ~{round(sum(r['dyn_ctx'] for r in rows) / len(rows))} tok, "
          f"native {round(sum(r['nat_ctx'] for r in rows) / len(rows))} tok")
    out = SCRATCH / "report.json"
    out.write_text(json.dumps(rows, indent=1))
    print("report:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
