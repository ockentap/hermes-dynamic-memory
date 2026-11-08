#!/usr/bin/env python3
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
"""Split one fat memory file into a hub plus engrams, from an explicit plan.

The file being split BECOMES the hub, so the index line does not change and the
first hop is untouched. Leaves are new files with a `Part of:` header and no
index line. Dry-run by default; `--apply` writes, validates with
`verify_index.py --tree --max-depth 5`, and rolls back on any failure.

Plan format (line ranges must cover the file exactly, 1..N, no gaps):

  {
    "hub_title": "Medivia — routing card",
    "hub_intro": "Read this, then one engram.",
    "synapse_keywords": "medivia,status,protocol,quests,log",
    "engrams": [
      {"file": "medivia-status.md", "start": 1, "end": 147,
       "keywords": "status,shipped,next,milestone,backlog",
       "when": "asking where the project stands, what shipped or what is next"},
      {"file": "medivia-frame.md", "start": 148, "end": 358,
       "keywords": "frame,map,offsets,npc,placement",
       "when": "working on the map frame, offsets or NPC placement"}
    ]
  }

`synapse_keywords` / `keywords` are optional: when present they are validated
(5-20, no spaces, no repeats, no marker) and written as the file's first line,
which is what `verify_index.py --keywords` expects. A tier may reuse words from
the tier above; the first five on every line are the optimizer's locked block.
The old key `hub_keywords` is still accepted.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from typing import NoReturn

MAX_ENGRAMS = 5
MAX_DEPTH = 5
MIN_KEYWORDS, MAX_KEYWORDS = 5, 20


def validate_keywords(raw, where: str) -> list[str] | None:
    """Validate an optional keyword block for a synapse or engram.

    Every tier carries the same band as the index: 5-20 keywords, no spaces
    inside one, no repeats, and no marker — markers are index-only. The first
    five are the optimizer's locked block; they are positional, so a plan only
    supplies the words.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        kws = [k.strip() for k in raw.split(",") if k.strip()]
    elif isinstance(raw, (list, tuple)):
        kws = [str(k).strip() for k in raw if str(k).strip()]
    else:
        die(f"{where}: keywords must be a comma string or a list")
    if kws and kws[0].startswith("!"):
        die(f"{where}: markers (!, !!, !!!) belong in the index, not on a neuron")
    if not (MIN_KEYWORDS <= len(kws) <= MAX_KEYWORDS):
        die(f"{where}: {len(kws)} keywords, need {MIN_KEYWORDS}-{MAX_KEYWORDS}")
    if len(kws) != len(set(kws)):
        die(f"{where}: duplicate keywords")
    for k in kws:
        if " " in k or len(k) > 48:
            die(f"{where}: keyword has a space or is too long: {k!r}")
    return kws


def die(msg: str) -> NoReturn:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def load_plan(path: str) -> dict:
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read plan {path}: {exc}")


def validate_plan(plan: dict, nlines: int, hub_name: str) -> list[dict]:
    engrams = plan.get("engrams")
    if not isinstance(engrams, list) or not engrams:
        die("plan.engrams must be a non-empty list")
    if len(engrams) > MAX_ENGRAMS:
        die(f"{len(engrams)} engrams > {MAX_ENGRAMS}; merge some sections")
    seen, total = set(), 0
    for i, engram in enumerate(engrams):
        f = engram.get("file", "")
        if not f.endswith(".md") or "/" in f or f == hub_name:
            die(f"engram[{i}].file must be a bare .md name, not the hub: {f!r}")
        if f in seen:
            die(f"duplicate engram file {f}")
        seen.add(f)
        if len(str(engram.get("when", "")).split()) < 4:
            die(f"engram[{i}].when must be at least 4 words")
        try:
            a, b = int(engram["start"]), int(engram["end"])
        except Exception:
            die(f"engram[{i}] needs integer start/end")
        if a < 1 or b < a or b > nlines:
            die(f"engram[{i}] range {a}-{b} outside 1..{nlines}")
        total += b - a + 1
    ordered = sorted(engrams, key=lambda x: int(x["start"]))
    expect = 1
    for engram in ordered:
        if int(engram["start"]) != expect:
            die(f"gap/overlap at line {expect}: engram {engram['file']} starts {engram['start']}")
        expect = int(engram["end"]) + 1
    if expect != nlines + 1:
        die(f"plan covers to line {expect - 1}, file has {nlines}")
    # `synapse_keywords` is the current name; `hub_keywords` stays accepted so a
    # plan written before the nomenclature rename keeps working.
    plan["_synapse_keywords"] = validate_keywords(
        plan.get("synapse_keywords", plan.get("hub_keywords")), "synapse_keywords")
    for i, engram in enumerate(engrams):
        engram["_keywords"] = validate_keywords(engram.get("keywords"), f"engram[{i}]")
    return ordered


def hub_text(plan: dict, engrams: list[dict], hub_name: str) -> str:
    title = plan.get("hub_title") or hub_name[:-3].replace("-", " ").title()
    intro = plan.get("hub_intro") or "Read this, then one engram."
    # A synapse is a router: one route line per child, keywords -> child.md.
    out = []
    for engram in engrams:
        kws = engram.get("_keywords") or [engram["file"][:-3]]
        out.append(f"{' '.join(kws)} → {engram['file']}")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="the fat topic file to split")
    ap.add_argument("--plan", required=True, help="JSON plan (see module docstring)")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    src = os.path.abspath(args.file)
    if not os.path.isfile(src):
        die(f"not a file: {src}")
    memdir = os.path.dirname(src)
    hub_name = os.path.basename(src)
    lines = open(src, encoding="utf-8").read().splitlines(keepends=True)
    plan = load_plan(args.plan)
    engrams = validate_plan(plan, len(lines), hub_name)
    hub = hub_text(plan, engrams, hub_name)

    print(f"source: {src} ({len(lines)} lines, {os.path.getsize(src)} bytes)")
    print(f"hub   : {hub_name}")
    for engram in engrams:
        n = int(engram["end"]) - int(engram["start"]) + 1
        print(f"  engram {engram['file']:40s} lines {engram['start']:4d}-{engram['end']:<4d} ({n:4d})  when {engram['when']}")
    print(f"hub edges: {len(engrams)}/{MAX_ENGRAMS}")

    if not args.apply:
        print("\n--- hub preview ---")
        print(hub)
        print("dry run: nothing written. Re-run with --apply.")
        return 0

    backup = os.path.join(os.path.expanduser("~/.hermes/backups"),
                          f"split-{time.strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(backup, exist_ok=True)
    shutil.copy2(src, os.path.join(backup, hub_name))
    created: list[str] = []
    try:
        for engram in engrams:
            body = "".join(lines[int(engram["start"]) - 1:int(engram["end"])])
            kw = engram.get("_keywords")
            header = f"# {engram['file'][:-3].replace('-', ' ').title()}\nPart of: {hub_name}.\n\n"
            path = os.path.join(memdir, engram["file"])
            if os.path.exists(path):
                die(f"engram already exists: {path}")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(header + body.rstrip() + "\n")
            created.append(path)
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(hub)

        index = os.path.join(memdir, "MEMORY.md")
        verify = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_index.py")
        cmd = [sys.executable, verify, index, "--tree", "--max-depth", str(MAX_DEPTH)]
        if plan.get("_synapse_keywords") and all(l.get("_keywords") for l in engrams):
            cmd.append("--keywords")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("validator failed:\n" + (r.stdout or "")[-1500:] + (r.stderr or "")[-500:])
        print(f"\napplied; backup at {backup}")
        for prefix in ("tree:", "keywords:"):
            line = [l for l in r.stdout.splitlines() if l.startswith(prefix)][-1:]
            if line:
                print(line[0])
        return 0
    except Exception as exc:
        for p in created:
            try:
                os.unlink(p)
            except OSError:
                pass
        shutil.copy2(os.path.join(backup, hub_name), src)
        print(f"ROLLED BACK: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
