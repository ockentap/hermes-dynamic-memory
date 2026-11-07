#!/usr/bin/env python3
"""Collapse filename families into a synapse plus children.

A family is several indexed files whose names start with the same token
(mempalace-oracle, mempalace-remine). Both claim the family word, and one word
may only route to one file per table. The split: one parent line holds the
family word, the siblings become its children, and the parent's `when` clauses
separate them. The children leave the index, so the index gets shorter and the
family word stops competing with itself.

Parent = a new `<family>.md` routing card, or an existing member when one is
the general file (`promote`). Dry-run by default; --apply backs up first.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import time

ARROW = "\u2192"

PLAN = {
    "user-routing.md": {
        "title": "User — routing card",
        "keywords": "user,persona,tone,preferences,workflow",
        "intro": "Who Lav is, how he wants to be answered, what he works on, and how he runs the day.",
        "children": [
            ("user-profile.md", "the question is about who Lav is, his background or his legal and health profile"),
            ("user-preferences.md", "the question is about how he wants answers written or what to avoid"),
            ("user-environment.md", "the question is about his machine, shell, editors or hardware"),
            ("user-workflow-preferences.md", "the question is about his working rhythm, cron habits or delivery preferences"),
        ],
    },
    "hermes-agent-config.md": {
        "promote": True,
        "children": [
            ("hermes-local-divergence.md", "the question is about the local fork, upgrades or divergence from upstream"),
            ("hermes-fd-exhaustion.md", "the question is about file-descriptor exhaustion or a gateway that stops accepting work"),
        ],
    },
    "pi-hermes.md": {
        "promote": True,
        "children": [
            ("pi-hermes-backup.md", "the question is about the nightly Pi backup or restoring from it"),
            ("pi-btnoise-speaker.md", "the question is about the Bluetooth speaker, white noise or bluealsa"),
        ],
    },
    "jev.md": {
        "title": "Jev — routing card",
        "keywords": "jev,journal,retrieval,classifier,typesafe",
        "intro": "The Jev retrieval stack: its classifier, its installed state, and the typesafe decision model.",
        "children": [
            ("jev-classifier.md", "the question is about the classifier, the memory router or keyless mode"),
            ("jev-install-state-2026-09-21.md", "the question is about what is installed, enabled or shadowed right now"),
            ("jev-typesafe.md", "the question is about typesafe.ai, the decision primitive or calibration"),
        ],
    },
    "gateway.md": {
        "title": "Hermes gateway — routing card",
        "keywords": "gateway,restart,service,webhook,listener",
        "intro": "Restarting the gateway, and the ways it fights back.",
        "children": [
            ("gateway-restart.md", "the question is about restarting the gateway or why it is blocked"),
            ("gateway-auto-attach-hazard.md", "the question is about files being attached to replies or a leaked path"),
        ],
    },
    "darkswords-project.md": {
        "promote": True,
        "children": [
            ("darkswords-standing-goal.md", "the question is about the standing goal, fidelity or wire parity"),
        ],
    },
    "x.md": {
        "title": "X — routing card",
        "keywords": "x,ockentap,posting,tweet,cdp",
        "intro": "The X account: how the browser holds it, and how the posting lanes run.",
        "children": [
            ("x-account-browser-access.md", "the question is about the logged-in browser, CDP or the session"),
            ("x-browser-runtime.md", "the question is about the pinned venv, playwright or runtime errors"),
        ],
    },
    "optiplex7050.md": {
        "title": "OptiPlex 7050 — routing card",
        "keywords": "optiplex7050,box,disk,scrub,btrfs",
        "intro": "The home box: the Hermes instance on it, and the data disk behind it.",
        "children": [
            ("optiplex7050-hermes-instance.md", "the question is about the Hermes install, its gateway or its backups"),
            ("optiplex7050-btrfs-data-disk.md", "the question is about the data disk, btrfs, dedupe or a scrub"),
        ],
    },
    "subagent.md": {
        "title": "Subagents — routing card",
        "keywords": "subagent,dispatch,isolation,tier,child",
        "intro": "How work is handed to a child agent, and what the child can and cannot see.",
        "children": [
            ("subagent-memory-isolation.md", "the question is about what a child inherits or why it confabulates"),
            ("subagent-tier-dispatch.md", "the question is about tiers, escalation or delegation_tiers.yaml"),
        ],
    },
    "bih.md": {
        "title": "Bosnia — routing card",
        "keywords": "bih,permit,canton,benefits,tcl",
        "intro": "Bosnian paperwork: social benefits and permits, and the TV purchase.",
        "children": [
            ("bih-benefits-and-permits-scanner.md", "the question is about benefits, permits or the scanner job"),
            ("bih-tv-2026-09.md", "the question is about the TCL TV, its warranty or the shops"),
        ],
    },
    "mempalace.md": {
        "title": "Mempalace — routing card",
        "keywords": "mempalace,palace,chromadb,drawers,cosine_sim",
        "intro": "The memory archive service: where it lives, and the job that keeps refilling it.",
        "children": [
            ("mempalace-oracle.md", "the question is about the server, its path, the MCP wiring or the search"),
            ("mempalace-remine.md", "the question is about the hourly remine job, its queue or its failures"),
        ],
    },
    "cloakbrowser.md": {
        "promote": True,
        "children": [
            ("cloakbrowser-default-browser.md", "the question is about making it the default browser or bot checks"),
        ],
    },
    "gemini.md": {
        "title": "Gemini — routing card",
        "keywords": "gemini,thought,native,language,vertex",
        "intro": "Two Gemini problems: the language guard, and the thought-signature 400.",
        "children": [
            ("gemini-language-guard.md", "the question is about the language guard or a middleware fault"),
            ("gemini-native-400-thought-signature.md", "the question is about a 400 from the native API or thought signatures"),
        ],
    },
    "falloutpythons.md": {
        "title": "Fallout Pythons — routing card",
        "keywords": "falloutpythons,shelter,rooms,playtest,savegame",
        "intro": "The Fallout Shelter clone: how it is worked on, and the bugs already paid for.",
        "children": [
            ("falloutpythons-workflow.md", "the question is about modules, the main loop or the playtest harness"),
            ("falloutpythons-bugs.md", "the question is about a known bug, room uid or savegame quirk"),
        ],
    },
}


def parse(line: str):
    if ARROW not in line or line.strip().startswith("#"):
        return None
    kw, tgt = line.rsplit(ARROW, 1)
    tgt = tgt.strip()
    if not tgt.endswith(".md"):
        return None
    return [k.strip() for k in kw.split(",") if k.strip()], tgt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--shadow", default=None)
    args = ap.parse_args()

    src = pathlib.Path(args.store).expanduser()
    store = src
    if args.shadow:
        store = pathlib.Path(args.shadow).expanduser()
        if store.exists():
            shutil.rmtree(store)
        shutil.copytree(src, store)
        print(f"shadow: {store}")

    index_path = store / "MEMORY.md"
    lines = index_path.read_text(encoding="utf-8").splitlines()
    head_end = 0
    for i, l in enumerate(lines):
        if l.strip().startswith("keyword,keyword,keyword"):
            head_end = i + 1
            break
    head = lines[:head_end]
    entries = []  # (line, kws, target)
    for line in lines[head_end:]:
        e = parse(line)
        if e:
            entries.append((line, e[0], e[1]))
    by_target = {t: (line, kws) for line, kws, t in entries}

    child_targets = set()
    child_to_parent = {}
    for parent, spec in PLAN.items():
        for f, _ in spec["children"]:
            child_targets.add(f)
            child_to_parent[f] = parent
    for parent, spec in PLAN.items():
        if spec.get("promote") and parent not in by_target:
            print(f"ERROR: promoted parent {parent} is not indexed", file=sys.stderr)
            return 1
    missing = child_targets - set(by_target)
    if missing:
        print(f"ERROR: families name files that are not indexed: {sorted(missing)}", file=sys.stderr)
        return 1

    out: list[str] = []
    emitted = set()
    for line, kws, target in entries:
        if target in child_to_parent:
            parent = child_to_parent[target]
            spec = PLAN[parent]
            if not spec.get("promote") and parent not in emitted:
                out.append(spec["keywords"] + " " + ARROW + " " + parent)
                emitted.add(parent)
            continue
        out.append(line)

    # promoted parents keep their line; new parents were emitted above
    print(f"index: {len(entries)} -> {len(out)} lines "
          f"(-{len(child_targets)} children, +{sum(1 for p,s in PLAN.items() if not s.get('promote'))} synapses)")

    if not args.apply:
        for parent, spec in PLAN.items():
            if not spec.get("promote"):
                print(f"  new {parent:26s} ← {', '.join(c for c, _ in spec['children'])}")
            else:
                print(f"  {parent:30s} ← {', '.join(c for c, _ in spec['children'])}")
        print("dry run: nothing written.")
        return 0

    backup = store / f"split-families-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copytree(store, backup, ignore=shutil.ignore_patterns("MEMORY.md.bak*", "split-families-*"))
    for parent, spec in PLAN.items():
        p = store / parent
        if spec.get("promote"):
            text = p.read_text(encoding="utf-8")
            if "## Related memories" in text:
                print(f"WARN {parent} already has Related memories; leaving it", file=sys.stderr)
                continue
            block = "\n## Related memories\n" + "\n".join(
                f"- when {w} → {c}" for c, w in spec["children"]) + "\n"
            p.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
            continue
        body = [f"keywords: {spec['keywords']}", f"# {spec['title']}", "", spec["intro"],
                "", "## Related memories"]
        body += [f"- when {w} → {c}" for c, w in spec["children"]]
        p.write_text("\n".join(body) + "\n", encoding="utf-8")

    index_path.write_text("\n".join(head + out) + "\n", encoding="utf-8")

    def seed(path: pathlib.Path, kws: list[str]) -> None:
        text = path.read_text(encoding="utf-8")
        first = next((l for l in text.splitlines() if l.strip()), "")
        if first.strip().lower().startswith("keywords:"):
            return
        clean = [k.strip().lstrip("!") for k in kws]
        path.write_text("keywords: " + ",".join(clean[:20]) + "\n" + text, encoding="utf-8")

    for line, kws, target in entries:
        if target in child_to_parent:
            continue
        seed(store / target, kws[:5])
    for child, parent in child_to_parent.items():
        old = by_target.get(child)
        if old:
            seed(store / child, old[1])
    print(f"seeded keyword lines for indexed neurons and {len(child_to_parent)} children")
    print(f"applied; backup dir {backup}")

    verify = pathlib.Path(__file__).with_name("verify_index.py")
    r = subprocess.run([sys.executable, str(verify), str(index_path), "--memdir", str(store),
                        "--tree", "--keywords"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.startswith(("  [FAIL]", "tree:", "keywords:")):
            print(line)
    print(f"validator exit: {r.returncode}")
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
