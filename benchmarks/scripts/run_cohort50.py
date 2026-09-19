#!/usr/bin/env python3
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
# See the NOTICE file for attribution requirements.
"""Cohort benchmark: 50 distinct memories, 50 plain questions.

Reproduces the result in docs/cohort-50.md (native 29/50, dynamic 46/50).

Usage:
  python3 run_cohort50.py --native <container> --dynamic <container> \
      [--out DIR] [--repeats N]

Both containers MUST be freshly built from the keeper images and contain no
session history. The script asserts this before writing memories, because a
contaminated container silently answers from state.db instead of memory and
produces a meaningless result.

  docker run -d --name clean-native  --hostname clean-native  \
      -e DEEPSEEK_API_KEY=...  hermes-native:0.21.3   sleep infinity
  docker run -d --name clean-dynamic --hostname clean-dynamic \
      -e DEEPSEEK_API_KEY=...  hermes-dynmem:1.4.3    sleep infinity
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import (adjudicate, ask, assert_clean, clean_container,
                     install_dynamic, install_native, score, strip_meta)

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "..", "fixtures", "cohort50.json")

CATEGORY_KEYWORDS = {
    "preference":  "preference,style,workflow,editor,shell,habits,convention,taste",
    "background":  "background,identity,locale,language,country,timezone,role,history",
    "environment": "environment,machine,hardware,os,terminal,tools,devices,setup",
    "work":        "work,engineering,stack,platform,deployment,monitoring,process,team",
    "logistics":   "logistics,personal,health,routine,travel,diet,hobbies,life",
}

# One natural question per memory, plus the distinctive tokens that prove recall.
# Questions deliberately avoid the category keyword, so a correct answer requires
# finding the memory rather than pattern-matching the topic name.
PROBES = {
 "pref_editor":   ("what editor do I use?", ["neovim", "nvim"]),
 "pref_shell":    ("what shell do I use?", ["fish"]),
 "pref_theme":    ("what's my preference for UI themes?", ["dark", "grey", "gray", "black"]),
 "pref_meetings": ("when shouldn't people book meetings with me?", ["10", "ten"]),
 "pref_commits":  ("how do I like my commit messages formatted?", ["conventional", "feat:", "fix:"]),
 "pref_coffee":   ("what's my coffee order?", ["espresso", "double", "no sugar"]),
 "pref_docs":     ("how do I prefer documentation to be written?", ["prose", "bullet"]),
 "pref_tests":    ("when do I want tests written?", ["before"]),
 "pref_reviews":  ("how do I review pull requests?", ["diff"]),
 "pref_speed":    ("what do I think about spinners and progress bars?", ["spinner", "progress", "plain"]),
 "pref_notes":    ("how do I take notes?", ["plain text", "text file"]),
 "pref_arch":     ("what's my stance on new frameworks?", ["boring", "proven"]),
 "bg_country":    ("what country do I live in?", ["portugal", "lisbon"]),
 "bg_lang_pt":    ("do I speak any languages besides english?", ["portuguese", "português"]),
 "bg_lang_de":    ("what's my level in german?", ["conversational", "berlin"]),
 "bg_role":       ("what do I do for a living?", ["backend", "platform"]),
 "bg_edu":        ("what did I study?", ["physics"]),
 "bg_employer":   ("what industry does my employer work in?", ["payment"]),
 "bg_tz":         ("what timezone am I in?", ["lisbon", "wet", "west"]),
 "bg_home_net":   ("what do I run at home network-wise?", ["dns", "vpn", "home lab", "homelab"]),
 "env_machine":   ("what laptop do I use?", ["m2", "macbook"]),
 "env_os":        ("what operating systems do I run?", ["macos", "debian"]),
 "env_homeserver":("what's my home server spec?", ["n100", "mini"]),
 "env_terminal":  ("what terminal do I use?", ["ghostty"]),
 "env_font":      ("what font and size do I use in the terminal?", ["jetbrains mono", "13"]),
 "env_keyboard":  ("what keyboard do I type on?", ["split", "ortholinear"]),
 "env_editor_cfg":("how do I manage my dotfiles?", ["bare git", "git repo"]),
 "env_backup":    ("how do I back up my personal files?", ["usb", "ssd", "monthly"]),
 "env_gpu":       ("do I have a discrete GPU?", ["no", "none"]),
 "env_phone":     ("what phone do I use?", ["android", "de-googled", "google"]),
 "env_browser":   ("what browser do I use?", ["firefox"]),
 "env_ci":        ("what CI do I use for work and for home?", ["github actions", "forgejo"]),
 "wk_vcs":        ("how do I like to merge code?", ["rebase", "squash"]),
 "wk_branch":     ("how do I name branches?", ["pay-", "ticket", "prefix"]),
 "wk_lang":       ("what languages do I write most?", ["go", "python"]),
 "wk_db":         ("what databases do we use?", ["postgres", "clickhouse"]),
 "wk_queue":      ("what message broker do we use?", ["kafka"]),
 "wk_deploy":     ("how do we deploy?", ["kubernetes", "on-prem", "on prem"]),
 "wk_secrets":    ("how do we handle secrets?", ["vault"]),
 "wk_monitoring": ("what's our monitoring stack?", ["prometheus", "grafana", "pagerduty"]),
 "wk_incident":   ("where do incidents get coordinated?", ["slack", "inc-", "postmortem"]),
 "wk_docs_where": ("where does internal documentation live?", ["wiki"]),
 "lg_travel":     ("where do I travel regularly?", ["berlin"]),
 "lg_diet":       ("what's my diet?", ["vegetarian", "fish"]),
 "lg_sleep":      ("what are my sleep hours?", ["06:30", "6:30", "22:30", "10:30"]),
 "lg_sport":      ("what exercise do I do?", ["run", "half marathon", "november"]),
 "lg_pets":       ("do I have any pets?", ["cat", "miso"]),
 "lg_drinks":     ("what do I drink at work events?", ["water", "alcohol"]),
 "lg_reading":    ("what do I read?", ["science fiction", "culture"]),
 "lg_finance":    ("how do I track my spending?", ["spreadsheet"]),
}

# Human adjudications applied over the mechanical score. Produced by READING each
# failing transcript. Every entry needs a reason. See docs/cohort-50.md, which
# documents the three automated graders that disagreed before this step existed.
ADJUDICATIONS = {
    ("pref_shell", "native"):    (True, "answered the fact; denial was about extra detail"),
    ("bg_lang_de", "native"):    (True, "asserted 'conversational, picked it up in Berlin'"),
    ("bg_home_net", "native"):   (True, "asserted the DNS resolver + VPN"),
    ("pref_notes", "native"):    (True, "asserted plain text files over a note app"),
    # native invented a branch convention it did not have, then admitted it
    ("wk_branch", "native"):     (False, "FABRICATED a convention, then admitted not stored"),
    ("pref_meetings", "dynamic"):(True, "asserted the 10am rule"),
    ("bg_edu", "dynamic"):       (True, "asserted physics"),
    ("wk_secrets", "dynamic"):   (True, "asserted Vault"),
    ("wk_docs_where", "dynamic"):(True, "asserted wiki"),
    ("lg_finance", "dynamic"):   (True, "asserted spreadsheet"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--native", default="clean-native")
    ap.add_argument("--dynamic", default="clean-dynamic")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "results", "cohort-50"))
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--verify-only", action="store_true",
                    help="re-score committed results instead of re-running the agents")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    memories = json.load(open(FIXTURE))
    cats: dict[str, list[dict]] = {}
    for m in memories:
        cats.setdefault(m["cat"], []).append(m)

    if args.verify_only:
        # Read the COMMITTED verdicts and just re-tally them. Do NOT re-derive
        # from the mechanical scores: adjudication was performed by hand across
        # three failed graders, and recomputing from the regex alone reproduces
        # the mechanical (wrong) number instead of the published one.
        rows = json.load(open(os.path.join(args.out, "answers-adjudicated.json")))
        for r in rows:
            r.setdefault("id", r.get("fact"))
        tally = {
            "native": sum(1 for r in rows if r.get("native_final")),
            "dynamic": sum(1 for r in rows if r.get("dynamic_final")),
            "total": len(rows),
        }
        print(f"native  : {tally['native']}/{tally['total']}")
        print(f"dynamic : {tally['dynamic']}/{tally['total']}")
        return 0

    print("rebuilding containers and wiping session state")
    for name in (args.native, args.dynamic):
        clean_container(name)
        assert_clean(name)

    print("\ninstalling 50 memories")
    install_dynamic(args.dynamic, cats, CATEGORY_KEYWORDS)
    nat = install_native(args.native, memories)
    print(f"  dynamic: {len(cats)} topic files, all {len(memories)} memories")
    print(f"  native : stored {len(nat['accepted'])}/{len(memories)} "
          f"({nat['chars']} chars), REFUSED {len(nat['refused'])}")

    rows = []
    for m in memories:
        mid = m["id"]
        prompt, needles = PROBES[mid]
        row = {"id": mid, "category": m["cat"], "question": prompt, "fact": m["text"],
               "needles": needles, "native_stored": mid in nat["accepted"]}
        print(f"  {mid:16s}", end="", flush=True)
        for container, who in ((args.native, "native"), (args.dynamic, "dynamic")):
            answers = []
            for _ in range(args.repeats):
                try:
                    answers.append(strip_meta(ask(container, prompt)))
                except Exception as e:  # noqa: BLE001
                    answers.append(f"(ERROR {e})")
            with open(f"{args.out}/{mid}.{who}.txt", "w") as f:
                f.write("\n\n--- repeat ---\n\n".join(answers))
            ok, why = score(answers[0], needles)
            row[who], row[who + "_ok"], row[who + "_why"] = answers[0], ok, why
            if args.repeats > 1:
                row[who + "_all"] = [bool(score(a, needles)[0]) for a in answers]
            print(f"  {who[0]}:{'P' if ok else 'F'}", end="", flush=True)
        rows.append(row)
        print()

    json.dump(rows, open(f"{args.out}/answers-raw.json", "w"), indent=1)
    tally = adjudicate(rows, ADJUDICATIONS)
    json.dump(rows, open(f"{args.out}/answers-adjudicated.json", "w"), indent=1)
    json.dump(nat, open(f"{args.out}/native_cap.json", "w"), indent=1)

    print("\n" + "=" * 56)
    print("COHORT-50 RESULT")
    print("=" * 56)
    print(f"  native  : {tally['native']}/{tally['total']}")
    print(f"  dynamic : {tally['dynamic']}/{tally['total']}")
    sn = [r for r in rows if r["native_stored"]]
    rn = [r for r in rows if not r["native_stored"]]
    if sn:
        print(f"  native, facts that FIT the cap : "
              f"{sum(1 for r in sn if r['native_final'])}/{len(sn)}")
    if rn:
        print(f"  native, facts the cap REFUSED  : "
              f"{sum(1 for r in rn if r['native_final'])}/{len(rn)}")
    print("\n  NOTE: mechanical scores are advisory. Review every 'denial(' and")
    print("  'no-needle' row before quoting these numbers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
