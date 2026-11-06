#!/usr/bin/env python3
# memcheck_report — turn recorded self-reports into keyword evidence
#
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
#
# Read-only. Prints, for one store:
#   * how many tags were asked for vs answered (compliance — a silent feature
#     looks identical to a clean one without this number);
#   * which recorded claims failed validation, by problem;
#   * keyword demotions backed by a traceable `wrong` verdict;
#   * promotion candidates from `right` / used files;
#   * near-miss files from the turn-1 `rejected` field, which is the only place
#     a false attraction is visible at all.
#
# Usage:
#   python3 scripts/memcheck_report.py                      # ~/.hermes
#   python3 scripts/memcheck_report.py --home /tmp/memtest
#   python3 scripts/memcheck_report.py --json

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugin" / "dynmem"))

import memcheck  # noqa: E402


def load(home: Path) -> tuple[list[dict], dict]:
    samples = []
    p = memcheck.samples_path(home)
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(json.loads(line))
            except Exception:
                continue
    return samples, memcheck.load_state(home)


def asked_counts(state: dict) -> dict[str, int]:
    out = collections.Counter()
    for sess in state.values():
        if not isinstance(sess, dict):
            continue
        asks = sess.get("asks")
        if isinstance(asks, dict):
            for k, v in asks.items():
                try:
                    out[str(k)] += int(v)
                except Exception:
                    pass
    return dict(out)


def build_report(home: Path) -> dict:
    samples, state = load(home)
    scored = memcheck.score(samples)

    problems = collections.Counter()
    for s in samples:
        for p in s.get("problems") or []:
            problems[p] += 1

    verdicts = collections.Counter(s.get("verdict") or "-" for s in samples if s.get("t") == "2")

    rejected = collections.Counter()
    near_miss_hooks: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for s in samples:
        for f in memcheck.split_targets(s.get("rejected")):
            rejected[f] += 1
            if s.get("hook"):
                near_miss_hooks[f][str(s["hook"]).lower()] += 1

    asked = asked_counts(state)
    answered = collections.Counter(s.get("t") for s in samples)
    compliance = {}
    for kind in ("1", "2"):
        a = asked.get(kind, 0)
        r = answered.get(kind, 0)
        compliance[kind] = {"asked": a, "answered": r,
                            "rate": round(r / a, 3) if a else None}

    return {
        "samples": len(samples),
        "usable": scored["used"],
        "ignored": scored["ignored"],
        "verdicts": dict(verdicts),
        "compliance": compliance,
        "problems": dict(problems.most_common()),
        "review": scored.get("review", {}),
        "promote": scored["promote"],
        "ambiguous_hooks": scored.get("ambiguous_hooks", {}),
        "near_miss_files": dict(rejected.most_common(15)),
        "near_miss_hooks": {f: dict(c.most_common(5)) for f, c in near_miss_hooks.items()},
    }


def render(rep: dict) -> str:
    lines = []
    lines.append(f"samples: {rep['samples']}  usable: {rep['usable']}  ignored: {rep['ignored']}")
    c = rep["compliance"]
    for kind, label in (("1", "turn-1 observables"), ("2", "verdict tail")):
        row = c.get(kind, {})
        rate = row.get("rate")
        rate_s = "n/a" if rate is None else f"{rate:.0%}"
        lines.append(f"  {label:18s} asked {row.get('asked', 0):4d}  answered {row.get('answered', 0):4d}  compliance {rate_s}")
    v = rep["verdicts"]
    if v:
        lines.append("  verdicts: " + "  ".join(f"{k}={n}" for k, n in v.items()))
    if rep["problems"]:
        lines.append("rejected claims: " + "  ".join(f"{k}={n}" for k, n in rep["problems"].items()))
    if rep.get("review"):
        lines.append("review by hand (blamed keyword; check that demoting it would not "
                     "break the line that routed correctly):")
        for f, kws in sorted(rep["review"].items()):
            lines.append(f"  {f}: " + ", ".join(f"{k} {v:+.0f}" for k, v in sorted(kws.items())))
    if rep["promote"]:
        lines.append("promote (2+ clean positives):")
        for f, terms in sorted(rep["promote"].items()):
            lines.append(f"  {f}: " + ", ".join(sorted(terms)))
    if rep.get("ambiguous_hooks"):
        lines.append("collisions (blamed word also on the correct line — disambiguate, never demote):")
        for f, n in sorted(rep["ambiguous_hooks"].items()):
            lines.append(f"  {f}  ×{n}")
    if rep["near_miss_files"]:
        lines.append("near-miss files (turn-1 rejected — review the hook word):")
        for f, n in rep["near_miss_files"].items():
            hooks = rep["near_miss_hooks"].get(f, {})
            hs = ("  hooks: " + ", ".join(f"{k}×{c}" for k, c in hooks.items())) if hooks else ""
            lines.append(f"  {f}  ×{n}{hs}")
    if not any([rep.get("review"), rep["promote"], rep["near_miss_files"]]):
        lines.append("no actionable evidence yet")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Report memcheck evidence")
    ap.add_argument("--home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rep = build_report(Path(args.home))
    print(json.dumps(rep, indent=2, ensure_ascii=False) if args.json else render(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
