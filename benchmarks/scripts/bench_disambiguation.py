#!/usr/bin/env python3
# bench_disambiguation — make the router trip, and watch it recover
#
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory.
#
# The index has no matcher: the model reads it and picks a file. So the only way
# to learn how it behaves under collision is to build collisions and watch.
#
# Twelve memories, three keywords each, one shared word per pair carrying two
# senses. Two prompt sets:
#
#   AMBIGUOUS  the shared word plus framing that belongs to neither line. Nothing
#              in the index can separate them, so the honest behaviour is to HEDGE
#              (pick one, name the other in 'also') or ask. A confident single pick
#              that is wrong is the failure mode: it feeds a wrong memory silently.
#   CLEAR      same pairs, a qualifier that appears on NEITHER line, so only what
#              the words mean can separate them.
#
# Condition "ambig+promoted" is the same ambiguous set with the qualifier promoted
# onto the correct line — the "add a keyword the user actually typed" move. If it
# does not reduce hedging, the promotion buys nothing on collisions.
#
# Stage two (`--stage correct`) is the recovery test: the user contradicts the
# pick, the real memcheck t2 tag rides the message, and the reply is parsed with
# the production parser. Measures compliance and whether the blamed `hook`
# survives validation.
#
# Usage:
#   python3 benchmarks/scripts/bench_disambiguation.py --stage route --runs 3
#   python3 benchmarks/scripts/bench_disambiguation.py --stage correct --runs 2
#
# Key comes from the process environment (OPENCODE_GO_API_KEY), never config.

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
sys.path.insert(0, str(REPO / "plugin" / "dynmem"))
import memcheck  # noqa: E402

# (shared word, (kws, file) sense A, (kws, file) sense B)
PAIRS = [
    ("bat", (["bat", "echolocation", "wing"], "fruit-bat.md"),
            (["bat", "championship", "stadium"], "baseball-bat.md")),
    ("python", (["python", "constrictor", "venom"], "python-snake.md"),
               (["python", "venv", "pip"], "python-toolchain.md")),
    ("jaguar", (["jaguar", "rosette", "amazon"], "jaguar-cat.md"),
               (["jaguar", "vin", "dealership"], "jaguar-car.md")),
    ("mercury", (["mercury", "orbit", "crater"], "mercury-planet.md"),
                (["mercury", "thermometer", "toxic"], "mercury-metal.md")),
    ("apple", (["apple", "orchard", "slicer"], "apple-fruit.md"),
              (["apple", "keynote", "appstore"], "apple-company.md")),
    ("java", (["java", "jvm", "spring"], "java-language.md"),
             (["java", "robusta", "island"], "java-coffee.md")),
    ("crane", (["crane", "bird", "migrate"], "crane-bird.md"),
              (["crane", "hoist", "site"], "crane-machine.md")),
    ("mouse", (["mouse", "rodent", "trap"], "mouse-animal.md"),
              (["mouse", "usb", "click"], "mouse-device.md")),
    ("shell", (["shell", "unix", "prompt"], "shell-unix.md"),
              (["shell", "petrol", "station"], "shell-company.md")),
    ("bank", (["bank", "river", "erosion"], "bank-river.md"),
             (["bank", "loan", "branch"], "bank-finance.md")),
    ("date", (["date", "palm", "fruit"], "date-fruit.md"),
             (["date", "calendar", "epoch"], "date-time.md")),
    ("coach", (["coach", "bus", "depot"], "coach-vehicle.md"),
              (["coach", "roster", "training"], "coach-trainer.md")),
]

# Genuinely two-way: the shared word plus framing that belongs to neither line.
AMBIGUOUS = [
    (1, "the bat everyone was talking about last night", "baseball-bat.md", "championship"),
    (2, "python is broken again and I have no idea why", "python-toolchain.md", "venv"),
    (3, "the jaguar needs a service and the parts are late", "jaguar-car.md", "dealership"),
    (4, "mercury levels in the sample are dangerous", "mercury-metal.md", "toxic"),
    (5, "apple is being replaced at the end of the month", "apple-company.md", "keynote"),
    (6, "java is too slow for what I am doing", "java-language.md", "jvm"),
    (7, "the crane is out of action until Tuesday", "crane-machine.md", "hoist"),
    (8, "the mouse is not responding again", "mouse-device.md", "usb"),
    (9, "shell says it is down for maintenance", "shell-company.md", "petrol"),
    (10, "the bank rejected it without telling me", "bank-finance.md", "loan"),
    (11, "the date is wrong on all of them", "date-time.md", "calendar"),
    (12, "the coach is being replaced after the season", "coach-trainer.md", "roster"),
]

# One-way: the qualifier appears on neither line, so only meaning separates them.
CLEAR = [
    (1, "the bat that hunts moths in the dark using sound", "fruit-bat.md", "moths"),
    (2, "the python that squeezes its prey until it stops breathing", "python-snake.md", "squeezes"),
    (3, "the jaguar that swims and cracks open turtle shells", "jaguar-cat.md", "turtle"),
    (4, "mercury is closest to the sun and has no atmosphere", "mercury-planet.md", "atmosphere"),
    (5, "apple takes a thirty percent cut of every sale in its store", "apple-company.md", "percent"),
    (6, "the crane that lifts steel beams onto the roof", "crane-machine.md", "steel"),
    (7, "my mouse cursor froze and the usb receiver is dead", "mouse-device.md", "cursor"),
    (8, "shell is where I type commands and get command not found", "shell-unix.md", "commands"),
    (9, "the bank where soil washes away when the river floods", "bank-river.md", "soil"),
    (10, "the date in the log is a unix timestamp I have to parse", "date-time.md", "timestamp"),
    (11, "the coach decides who starts and runs the training", "coach-trainer.md", "starts"),
    (12, "java runs on a jvm and every server can host it", "java-language.md", "jvm"),
]

HEADER = """# Memory Index — keyword,keyword,keyword → file.md

This is a keyword routing table, not the knowledge base. Each line maps keywords
to a topic file in the same directory. When a question matches a line, read that
file. Absence from this index is not absence of knowledge.
"""

INSTRUCTIONS = (
    "Route each request to the ONE topic file you would open, using only the index "
    "above. If two files compete and you cannot tell them apart, pick the more likely "
    "one and name the other in 'also'. Reply with JSON only:\n"
    '{"answers":[{"id":1,"file":"x.md","also":[],"confidence":0-100}]}\n'
    "No prose."
)


def all_entries() -> dict[str, list[str]]:
    out = {}
    for _, a, b in PAIRS:
        out[a[1]] = [k.lower() for k in a[0]]
        out[b[1]] = [k.lower() for k in b[0]]
    return out


def build_index(prompts, promote: bool) -> str:
    qual = {p[2]: p[3] for p in prompts} if promote else {}
    lines = [HEADER, "keyword,keyword,keyword → file.md"]
    for _, a, b in PAIRS:
        for kws, target in (a, b):
            row = list(kws)
            extra = qual.get(target)
            if extra and extra not in row:
                row.append(extra)
            lines.append(",".join(row) + " → " + target)
    return "\n".join(lines)


def bodies() -> dict[str, str]:
    return {f: f"# {f}\n\nStub body for {f}.\n" for f in all_entries()}


def call(system: str, user: str, session: str, max_tokens: int = 1400) -> str:
    import urllib.request

    key = os.environ.get("OPENCODE_GO_API_KEY") or os.environ.get("BENCH_API_KEY")
    if not key:
        raise SystemExit("OPENCODE_GO_API_KEY not set")
    body = {"model": MODEL,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens}
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}",
                 "User-Agent": "hermes-agent/bench",
                 "x-opencode-session": session})
    with urllib.request.urlopen(req, timeout=240) as fh:
        payload = json.loads(fh.read().decode())
    return payload["choices"][0]["message"]["content"]


def parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"no JSON: {text[:200]!r}")
    return json.loads(text[start:end + 1])


def score(payload: dict, prompts, label: str) -> dict:
    got = {int(a.get("id", 0)): a for a in payload.get("answers", []) if isinstance(a, dict)}
    rows = []
    for pid, prompt, gold, _q in prompts:
        a = got.get(pid) or {}
        pick = os.path.basename(str(a.get("file") or ""))
        also = [os.path.basename(str(x)) for x in (a.get("also") or []) if x]
        rows.append({"id": pid, "gold": gold, "pick": pick, "also": also,
                     "correct": pick == gold, "hedged": gold in also,
                     "conf": a.get("confidence")})
    return {
        "label": label, "n": len(rows),
        "at1": sum(r["correct"] for r in rows),
        "hedged_but_wrong": sum((not r["correct"]) and r["hedged"] for r in rows),
        "confident_wrong": sum((not r["correct"]) and not r["hedged"] for r in rows),
        "rows": rows,
    }


def reversed_prompts():
    """Same under-determined prompts, gold = the sense a model would NOT assume.

    The text cannot separate the two lines, so the answer lives in the user's head.
    This is the shape that trips: the model resolves by world prior, which is wrong
    whenever the user meant the other one, and it has no way to know.
    """
    sib = {}
    for _, a, b in PAIRS:
        sib[a[1]] = b[1]
        sib[b[1]] = a[1]
    return [(i, p, sib[g], q) for i, p, g, q in AMBIGUOUS]


def run_route(runs: int) -> dict:
    out = {}
    for label, prompts, promote in (("ambig", AMBIGUOUS, False),
                                    ("ambig-reversed", reversed_prompts(), False),
                                    ("ambig+promoted", AMBIGUOUS, True),
                                    ("clear", CLEAR, False)):
        system = build_index(prompts, promote) + "\n\n" + INSTRUCTIONS
        for run in range(1, runs + 1):
            try:
                raw = call(system, "\n".join(f"{i}. {q}" for i, q, _, _ in prompts),
                           f"bench-route-{label}-{run}")
                s = score(parse_json(raw), prompts, label)
            except Exception as exc:
                print(f"{label} run{run}: FAILED {exc}")
                continue
            out[f"{label}#{run}"] = s
            print(f"{label:15s} run{run}: @1 {s['at1']}/{s['n']}  "
                  f"confident-wrong {s['confident_wrong']}  hedged-wrong {s['hedged_but_wrong']}")
            for r in s["rows"]:
                if not r["correct"]:
                    print(f"    miss id={r['id']} gold={r['gold']} pick={r['pick']} "
                          f"also={r['also']} conf={r['conf']}")
    return out


def run_correct(runs: int) -> dict:
    """The correction turn: contradict the pick, ask with the real t2 tag."""
    entries = all_entries()
    bod = bodies()
    sibling = {}
    for _, a, b in PAIRS:
        sibling[a[1]] = b[1]
        sibling[b[1]] = a[1]
    tag = memcheck.T2_TEMPLATE
    results = []
    for run in range(1, runs + 1):
        for pid, prompt, gold, qualifier in AMBIGUOUS:
            wrong_pick = sibling[gold]  # the other sense of the same pair
            system = build_index(AMBIGUOUS, False) + "\n\n" + INSTRUCTIONS
            user = (f"Turn 1 user: {prompt}\n"
                    f"Turn 1 assistant: I would open {wrong_pick}.\n"
                    f"Turn 2 user: no, that's the other one - I meant the {qualifier} thing. "
                    f"Answer the question, then follow the instruction below.\n\n{tag}")
            try:
                raw = call(system, user, f"bench-correct-{run}-{pid}")
            except Exception as exc:
                results.append({"id": pid, "error": str(exc)})
                continue

            visible, raw_tag, misplaced = memcheck.split_tag(raw)
            sample = memcheck.parse_tag(raw_tag or "")
            sample["used_files"] = []
            problems = memcheck.validate(
                sample, entries, bod,
                [prompt, f"no, that's the other one - I meant the {qualifier} thing"])
            if misplaced:
                problems.append("text_after_tag")
            results.append({
                "id": pid, "gold": gold, "tag_present": bool(raw_tag),
                "parsed": {k: sample.get(k) for k in ("t", "verdict", "wrong", "right", "hook")},
                "problems": problems, "tag_leaked_into_visible": "<mc" in visible,
                "answer_len": len(visible),
            })
    from collections import Counter
    kinds = Counter(pr for r in results for pr in (r.get("problems") or []))
    ok = [r for r in results if not r.get("error")]
    present = sum(r["tag_present"] for r in ok)
    clean = sum(1 for r in ok if r["tag_present"] and not r["problems"])
    named_right = sum(1 for r in ok
                      if os.path.basename(str((r.get("parsed") or {}).get("right") or "")) == r["gold"])
    hook_ok = sum(1 for r in ok if r["tag_present"] and (r.get("parsed") or {}).get("hook")
                  and "hook_untraceable" not in r["problems"]
                  and "hook_without_file" not in r["problems"])
    print(f"correction turn: {len(ok)} replies  tag present {present}  clean {clean}  "
          f"named-right {named_right}  hook-traceable {hook_ok}")
    if kinds:
        print("  problems: " + "  ".join(f"{k}={v}" for k, v in kinds.most_common()))
    for r in ok:
        if r["problems"] or not r["tag_present"]:
            print(f"    id={r['id']} gold={r['gold']} parsed={r['parsed']} problems={r['problems']}")
    return {"summary": {"replies": len(ok), "tag_present": present, "clean": clean,
                        "named_right": named_right, "hook_traceable": hook_ok,
                        "problems": dict(kinds)},
            "rows": results}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["route", "correct"], default="route")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        for label, prompts, promote in (("ambig", AMBIGUOUS, False),
                                        ("ambig+promoted", AMBIGUOUS, True),
                                        ("clear", CLEAR, False)):
            s = build_index(prompts, promote) + "\n\n" + INSTRUCTIONS
            print(f"{label:15s} prompt {len(s)} chars ≈ {len(s)//4} tok, {len(prompts)} prompts")
        return 0

    out_dir = REPO / "benchmarks" / "results" / "memcheck-disambiguation"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    data = run_route(args.runs) if args.stage == "route" else run_correct(args.runs)
    (out_dir / f"{args.stage}-{stamp}.json").write_text(
        json.dumps({"model": MODEL, "stage": args.stage, "data": data}, indent=2),
        encoding="utf-8")
    print("saved", out_dir / f"{args.stage}-{stamp}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
