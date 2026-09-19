#!/usr/bin/env python3
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
# See the NOTICE file for attribution requirements.
"""Complexity benchmark: do verbose, structured memories survive?

Reproduces the result in docs/complexity.md (native 11/30, dynamic 30/30).

The cohort benchmark uses atomic one-line facts, which native stores verbatim —
so it tests COUNT, not compression. These six fixtures are decisions with
reasoning, exceptions, ordering constraints and names: the shape a lossy summary
destroys while keeping the headline. Each is probed for every detail it contains,
which separates "stored the gist" from "stored the memory".

Usage:
  python3 run_complexity.py --native <container> --dynamic <container> [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import (adjudicate, ask, assert_clean, benchmark_conditions,
                     clean_container, install_dynamic, install_native, load_results,
                     score, strip_meta)

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "..", "fixtures", "complex_facts.json")

# Index keywords for the six complex fixtures. NOTE: these average 7 keywords and
# 82 characters per line, which is what the benchmark actually measured. The README
# quotes a projected 12-keyword line (131 chars) as the conservative case.
FIXTURE_KEYWORDS = {
    "c1_expand_contract":   "migration,schema,rollback,backward-compatible,expand,contract",
    "c2_incident_severity": "severity,sev,incident,escalation,postmortem,page",
    "c3_deploy_ordering":   "deploy,canary,rollout,promote,threshold,rollback,ordering",
    "c4_access_control":    "access,permission,break-glass,production,contractor,write",
    "c5_retention_matrix":  "retention,deletion,gdpr,backup,pii,audit,expiry",
    "c6_oncall_escalation": "oncall,on-call,escalation,paging,fatigue,handover",
}

# Adjudications over the mechanical score, produced by reading each transcript.
# Three answers initially scored as passes and were overturned:
#   - two c3 answers were sourced to a LEFTOVER example file from an earlier run,
#     not to the complex fact
#   - one c5 answer explicitly disclaimed itself: "this is the general answer,
#     not a quote of your policy"
# Without these, native reads 14/30 and "3/19" instead of 11/30 and "0/19".
ADJUDICATIONS = {
    ("c3_deploy_ordering", "native"):   (False, "answered from leftover example file, not from memory"),
    ("c5_retention_matrix", "native"):  (False, "explicitly disclaimed: 'not a quote of your policy'"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--native", default="clean-native")
    ap.add_argument("--dynamic", default="clean-dynamic")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "results", "complexity"))
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    facts = json.load(open(FIXTURE))

    if args.verify_only:
        # Read the committed verdicts; do not re-derive from the mechanical score
        # (see the note in run_cohort50.py).
        path = os.path.join(args.out, "answers-adjudicated.json")
        cond = benchmark_conditions(path)
        if cond:
            print(f"run conditions: model={cond.get('model')} "
                  f"provider={cond.get('provider')} "
                  f"hermes={cond.get('hermes_version')} "
                  f"date={cond.get('date')}")
        rows = load_results(path)
        for r in rows:
            r.setdefault("id", r.get("fact"))
        tally = {
            "native": sum(1 for r in rows if r.get("native_final", r.get("native_ok"))),
            "dynamic": sum(1 for r in rows if r.get("dynamic_final", r.get("dynamic_ok"))),
            "total": len(rows),
        }
        print(f"native  : {tally['native']}/{tally['total']}")
        print(f"dynamic : {tally['dynamic']}/{tally['total']}")
        sn = [r for r in rows if r.get("native_stored")]
        rn = [r for r in rows if not r.get("native_stored")]
        if sn:
            print(f"  native stored  : "
                  f"{sum(1 for r in sn if r.get('native_final', r.get('native_ok')))}/{len(sn)}")
        if rn:
            print(f"  native refused : "
                  f"{sum(1 for r in rn if r.get('native_final', r.get('native_ok')))}/{len(rn)}")
        return 0

    print("rebuilding containers and wiping session state")
    for name in (args.native, args.dynamic):
        clean_container(name)
        assert_clean(name)

    # Each complex fixture is its own topic file, so detail lives on disk.
    cats = {f["id"]: [{"id": f["id"], "text": f["body"]}] for f in facts}
    total_chars = sum(f["chars"] for f in facts)
    print(f"\ninstalling {len(facts)} complex memories ({total_chars:,} chars)")
    install_dynamic(args.dynamic, cats, FIXTURE_KEYWORDS)
    nat = install_native(args.native, [{"id": f["id"], "text": f["body"]} for f in facts])
    print(f"  dynamic: {len(facts)} topic files, all facts at full detail")
    print(f"  native : stored {len(nat['accepted'])}/{len(facts)} "
          f"({nat['chars']} chars), REFUSED {len(nat['refused'])}")

    rows = []
    for f in facts:
        for question, needles, label in f["probes"]:
            row = {"id": f["id"], "fact": f["id"], "probe": label,
                   "question": question, "needles": needles,
                   "native_stored": f["id"] in nat["accepted"]}
            print(f"  {f['id'][3:]:18s} {label[:38]:40s}", end="", flush=True)
            for container, who in ((args.native, "native"), (args.dynamic, "dynamic")):
                try:
                    ans = strip_meta(ask(container, question))
                except Exception as e:  # noqa: BLE001
                    ans = f"(ERROR {e})"
                slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
                with open(f"{args.out}/{f['id']}__{slug}.{who}.txt", "w") as fh:
                    fh.write(ans)
                ok, why = score(ans, needles)
                row[who], row[who + "_ok"], row[who + "_why"] = ans, ok, why
                print(f" {who[0]}:{'P' if ok else 'F'}", end="", flush=True)
            rows.append(row)
            print()

    json.dump(rows, open(f"{args.out}/answers-raw.json", "w"), indent=1)
    tally = adjudicate(rows, ADJUDICATIONS)
    json.dump(rows, open(f"{args.out}/answers-adjudicated.json", "w"), indent=1)
    json.dump(nat, open(f"{args.out}/native_cap.json", "w"), indent=1)

    print("\n" + "=" * 60)
    print("COMPLEXITY RESULT (detail probes)")
    print("=" * 60)
    print(f"  native  : {tally['native']}/{tally['total']}")
    print(f"  dynamic : {tally['dynamic']}/{tally['total']}")
    sn = [r for r in rows if r["native_stored"]]
    rn = [r for r in rows if not r["native_stored"]]
    if sn:
        print(f"  native, facts it STORED  : {sum(1 for r in sn if r['native_final'])}/{len(sn)}")
    if rn:
        print(f"  native, facts it REFUSED : {sum(1 for r in rn if r['native_final'])}/{len(rn)}")
    print("\n  NOTE: mechanical scores are advisory — review 'denial(' and 'no-needle'")
    print("  rows by hand before quoting. Also make sure the container has no leftover")
    print("  example fixtures: two probes in the original run were answered from a")
    print("  stray examples/memories/deploy-pipeline.md left by an earlier benchmark.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
