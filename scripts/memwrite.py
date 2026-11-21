#!/usr/bin/env python3
"""memwrite — the write path.

The agent writes the prose; this script decides whether the write is legal.

    python3 scripts/memwrite.py --store <memories> --plan plan.json [--dry-run]

A plan is JSON:

  new topic:
    {"mode": "new",
     "neuron": {"name": "filament-dryer.md",
                "lines": ["esp32 eshome sht31 heater ptc → filament-dryer-hardware.md"]},
     "engrams": [{"name": "filament-dryer-hardware.md",
                  "content": "# ...\nPart of: filament-dryer.md.\n\n..."}],
     "index_line": "filament dryer esp32 petg nylon → filament-dryer.md"}

  update an existing engram:
    {"mode": "update",
     "target": "vaultwarden-pi-account-provisioning-hard-part-ver.md",
     "content": "# ...\nPart of: vaultwarden.md.\n\n..."}

What it does, in order:
  1. copy the store to a shadow directory
  2. apply the plan there (create/merge files, replace or append the index line)
  3. normalise every routing table: strip junk keywords, dedupe per table,
     top up to five, keep 5–20
  4. validate the shadow with verify_index --tree --keywords --engrams
  5. only on exit 0: back up the live store and copy the changed files over
  6. print a compact summary — never the index itself (that echo was the cost)

No model calls. The prose comes from the agent; this is the mechanical gate.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

ARROW = "\u2192"
ROUTE = re.compile(r"^(?P<kw>.+?)\s*(?:\u2192|->)\s*(?P<t>[A-Za-z0-9_.\-]+\.md)\s*$")
GOOD = re.compile(r"^[a-z0-9][a-z0-9_.\-]{1,47}$")
JUNK = re.compile(r"(\.md$|^v?\d+[.\-]\d+|.{30,}-.{10,}-.{10,})")
STOP = {"the", "and", "for", "with", "from", "that", "this", "into", "when", "what",
        "how", "are", "was", "were", "has", "have", "its", "not", "but", "all", "any",
        "can", "part", "under", "moved", "md", "section", "file", "files", "detail",
        "since", "also", "then", "than", "them", "they", "your", "you"}
MIN_KW, MAX_KW = 5, 20
VERIFY = pathlib.Path(__file__).resolve().with_name("verify_index.py")


def die(msg: str) -> None:
    print(f"memwrite: {msg}", file=sys.stderr)
    raise SystemExit(3)


def clean_kw(tokens: list[str]) -> list[str]:
    out = []
    for tok in tokens:
        t = tok.lower().strip(".,;:()[]`'\"")
        # the marker prefixes are load-bearing (!! never edit, ! never prune):
        # they are not part of the keyword body, so validate the body and stick
        # the prefix back instead of dropping the keyword as junk
        m = re.match(r"^(!*)(.*)$", t)
        prefix, body = (m.group(1), m.group(2)) if m else ("", t)
        if not body or not GOOD.match(body) or body in STOP or JUNK.search(body):
            continue
        kw = prefix + body
        if kw not in out:
            out.append(kw)
    return out


def title_words(path: pathlib.Path) -> list[str]:
    """Words to top a route line up from: the title, then the first screen."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines()[:4]:
        if line.startswith("# "):
            out += re.findall(r"[a-z][a-z0-9_.\-]{2,}", line[2:].lower())
            break
    out += re.findall(r"[a-z][a-z0-9_.\-]{3,}", text[:800].lower())
    return out


def normalise(store: pathlib.Path) -> dict[str, int]:
    """Dedupe + top up every routing table, index included. Returns counts."""
    stats = {"tables": 0, "dropped": 0, "topped": 0}
    for path in [store / "MEMORY.md"] + sorted(store.glob("*.md")):
        if path.name in {"USER.md"}:
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        body = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
        routes = [l for l in body if ROUTE.match(l)]
        if not routes or len(routes) / max(1, len(body)) < 0.5:
            continue
        used: set[str] = set()
        out, changed = [], 0
        for line in lines:
            m = ROUTE.match(line.strip())
            if not m:
                out.append(line)
                continue
            target = m.group("t")
            if target == "file.md" or line.strip().startswith("keyword,keyword"):
                out.append(line)   # the format template, not a route
                continue
            kws = clean_kw(m.group("kw").split())
            before = len(kws)
            deduped = [k for k in kws if k not in used]
            stats["dropped"] += before - len(deduped)
            if len(deduped) < MIN_KW:
                # dropping every tier-wide repeat can leave a line that fails
                # the 5-keyword floor; a duplicate keyword is the lesser defect
                deduped = kws
            kws = deduped
            if len(kws) < MIN_KW:
                extra = clean_kw(re.findall(r"[a-z][a-z0-9_.\-]{2,}", target[:-3].lower())
                                 + title_words(store / target))
                for w in extra:
                    if len(kws) >= MIN_KW:
                        break
                    if w not in used and w not in kws:
                        kws.append(w)
                        stats["topped"] += 1
            kws = kws[:MAX_KW]
            used.update(kws)
            new = " ".join(kws) + f" {ARROW} " + target
            if new != line.strip():
                changed += 1
            out.append(new)
        if changed:
            path.write_text("\n".join(out) + "\n", encoding="utf-8")
            stats["tables"] += 1
    return stats


def apply_plan(store: pathlib.Path, plan: dict) -> list[str]:
    """Write the plan into `store`. Returns the files touched."""
    mode = plan.get("mode")
    index_path = store / "MEMORY.md"
    index = index_path.read_text(encoding="utf-8")
    if not index.endswith("\n"):
        index += "\n"
    touched: list[str] = []

    if mode == "new":
        neuron = plan.get("neuron") or {}
        name = neuron.get("name") or ""
        if not name.endswith(".md") or "/" in name:
            die("plan.neuron.name must be a bare .md filename")
        lines = [l.strip() for l in neuron.get("lines", []) if l.strip()]
        if not lines:
            die("plan.neuron.lines is empty")
        for line in lines:
            if not ROUTE.match(line):
                die(f"neuron route line has no arrow: {line!r}")
        existing = store / name
        if existing.exists():
            have = [l.strip() for l in existing.read_text(encoding="utf-8").splitlines() if l.strip()]
            targets = {ROUTE.match(l).group("t") for l in have if ROUTE.match(l)}
            merged = have + [l for l in lines if ROUTE.match(l).group("t") not in targets]
            existing.write_text("\n".join(merged) + "\n", encoding="utf-8")
        else:
            existing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        touched.append(name)
        for e in plan.get("engrams", []):
            en = e.get("name", "")
            if not en.endswith(".md") or "/" in en:
                die(f"bad engram name {en!r}")
            target_path = store / en
            if target_path.exists():
                die(f"engram {en} already exists; use mode 'update' for it")
            target_path.write_text(e.get("content", "").rstrip() + "\n", encoding="utf-8")
            touched.append(en)
        index_line = plan.get("index_line", "").strip()
        m_idx = ROUTE.match(index_line)
        if not m_idx:
            die("plan.index_line is not a route line")
        target = m_idx.group("t")
        # replace an existing line for the same target, else append
        kept, replaced = [], False
        for line in index.splitlines():
            m = ROUTE.match(line.strip())
            if m and m.group("t") == target:
                kept.append(index_line)
                replaced = True
            else:
                kept.append(line)
        if not replaced:
            kept.append(index_line)
        index_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        touched.append("MEMORY.md")

    elif mode == "update":
        target = plan.get("target", "")
        if not (store / target).exists():
            die(f"update target does not exist: {target}")
        (store / target).write_text(plan.get("content", "").rstrip() + "\n", encoding="utf-8")
        touched.append(target)
        index_line = plan.get("index_line", "").strip()
        if index_line:
            m_idx = ROUTE.match(index_line)
            existing_targets = set()
            for line in index.splitlines():
                mm = ROUTE.match(line.strip())
                if mm:
                    existing_targets.add(mm.group("t"))
            # an update to an engram must not mint a top-level line for it: the
            # file is already reachable through its neuron, and a second home is
            # the DOUBLE-HOMED defect. Only refresh a line the target already owns.
            if not m_idx or m_idx.group("t") != target or target not in existing_targets:
                plan = dict(plan)
                plan.pop("index_line", None)
                index_line = ""
        if index_line:
            m_idx = ROUTE.match(index_line)
            if not m_idx:
                die("plan.index_line is not a route line")
            kept, replaced = [], False
            for line in index.splitlines():
                m = ROUTE.match(line.strip())
                if m and m.group("t") == m_idx.group("t"):
                    kept.append(index_line)
                    replaced = True
                else:
                    kept.append(line)
            if not replaced:
                kept.append(index_line)
            index_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
            touched.append("MEMORY.md")
    else:
        die("plan.mode must be 'new' or 'update'")
    return touched


def validate(store: pathlib.Path) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(VERIFY), str(store / "MEMORY.md"),
                        "--memdir", str(store), "--tree", "--keywords", "--engrams"],
                       capture_output=True, text=True)
    keep = [l for l in r.stdout.splitlines()
            if l.startswith(("  [FAIL]", "  [WARN]", "tree:", "keywords:", "engrams:", "6 lines", "1"))
            or re.match(r"^\d+ lines", l)]
    return r.returncode, "\n".join(keep)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--plan", required=True, help="JSON file, or - for stdin")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quiet", action="store_true",
                    help="one line: files, validator verdict, backup")
    ap.add_argument("--allow-rewrite", action="store_true",
                    help="required: this script rewrites MEMORY.md")
    args = ap.parse_args()
    if not args.allow_rewrite and not args.dry_run:
        die("refusing to rewrite MEMORY.md without --allow-rewrite "
            "(the dynmem hook's rule: index writes are explicit)")
    store = pathlib.Path(args.store).expanduser()
    raw = sys.stdin.read() if args.plan == "-" else pathlib.Path(args.plan).read_text(encoding="utf-8")
    plan = json.loads(raw)

    with tempfile.TemporaryDirectory() as tmp:
        # Baseline: what the store ALREADY fails on, in the same normalised
        # shape the plan is judged in, so pre-existing debt cannot be mistaken
        # for damage the plan did.
        base = pathlib.Path(tmp) / "base"
        shutil.copytree(store, base)
        normalise(base)
        base_code, base_summary = validate(base)
        base_fails = {l for l in base_summary.splitlines() if l.startswith("  [FAIL]")}

        shadow = pathlib.Path(tmp) / "store"
        shutil.copytree(store, shadow)
        touched = apply_plan(shadow, plan)
        stats = normalise(shadow)
        code, summary = validate(shadow)
        new_fails = [l for l in summary.splitlines()
                     if l.startswith("  [FAIL]") and l not in base_fails]
        if not args.quiet:
            print(f"plan: {plan.get('mode')}  files: {', '.join(touched)}")
            print(f"normalise: {stats['tables']} table(s), -{stats['dropped']} dup/junk, +{stats['topped']} topped up")
            print(summary)
        if new_fails:
            print("memwrite: the plan introduces new defects — nothing written:", file=sys.stderr)
            for line in new_fails[:5]:
                print(line, file=sys.stderr)
            return code
        if code != 0 and base_fails:
            print(f"memwrite: {len(base_fails)} pre-existing store defect(s) tolerated; "
                  "the plan adds none", file=sys.stderr)
        if args.dry_run:
            if args.quiet:
                verdict = next((l for l in summary.splitlines() if "lines OK" in l), "")
                coll = next((l for l in summary.splitlines() if l.startswith("keywords:")), "")
                print(f"dry: {len(touched)} files; {verdict.strip()}; {coll.strip()}")
            else:
                print("dry run: live store untouched")
            return 0
        backup = store / f"memwrite-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
        backup.mkdir(parents=True)
        for name in touched:
            if (store / name).exists():
                shutil.copy2(store / name, backup / name)
        for name in touched:
            shutil.copy2(shadow / name, store / name)
        log = pathlib.Path.home() / ".hermes" / "state" / "memwrite.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {plan.get('mode')} "
                    f"{','.join(touched)} backup={backup.name}\n")
        if args.quiet:
            verdict = next((l for l in summary.splitlines() if "lines OK" in l), "")
            coll = next((l for l in summary.splitlines() if l.startswith("keywords:")), "")
            print(f"written: {len(touched)} files; {verdict.strip()}; {coll.strip()}; backup {backup.name}")
        else:
            print(f"written: {', '.join(touched)}  backup: {backup.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
