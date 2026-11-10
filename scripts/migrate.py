#!/usr/bin/env python3
"""Migrate a flat dynmem store to the neuron (synapse) layout, agent-guided.

A flat store is `index -> engram` on every line. The token-cheap layout groups
those lines under synapses: `index -> synapse -> engram`. The grouping is a
judgement call (a script cannot tell which memories belong to one domain), so the
agent writes a plan and this tool executes the mechanics and proves nothing was
lost.

  migrate.py --store DIR --plan plan.json             # dry run (default)
  migrate.py --store DIR --plan plan.json --apply     # execute
  migrate.py --undo RUN_DIR                           # restore a run
  migrate.py --runs                                   # list runs

Safety, in order of use:
  A  full copy of the store            $HERMES_HOME/memories-backup/<run>/
  B  second copy off the store tree    ~/dynmem-migrations/<run>/store.tar.gz
  C  .orig copies the run rewrites     <A>/files/
  D  the frozen plan                   <B>/plan.json
  E  manifest: file hashes + line moves <B>/manifest.json
  F  --undo <run>                      restores A, refuses if the store moved

Two gates run before anything is published:
  * reachability — every memory reachable from the old index must be reachable
    from the new one (no memory silently orphaned);
  * validator — the staged store must pass `verify_index.py --tree --keywords`.
The plan is staged in a temp copy first; the real store is only touched when both
gates pass.

Copyright 2026 ockentap
SPDX-License-Identifier: Apache-2.0
Part of hermes-dynamic-memory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ARROW = "\u2192"
ROUTE_RE = re.compile(r"^(?P<kw>\S.*?)\s*\u2192\s*(?P<target>[A-Za-z0-9_.\-]+\.md)\s*$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+\.md$")
MIN_KW, MAX_KW = 5, 20


class PlanError(Exception):
    pass


def hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def default_store() -> Path:
    return hermes_home() / "memories"


def migration_root() -> Path:
    """Where the off-store copy, plan and manifest live (override for tests)."""
    return Path(os.environ.get("DYNMEM_MIGRATION_HOME") or (Path.home() / "dynmem-migrations"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def split_index(text: str) -> tuple[list[str], list[dict], list[str]]:
    """Return (leading lines, route entries, trailing non-route lines).

    Entries keep their line number so the rewrite can put a domain line where its
    first child used to be, leaving the rest of the file's order alone.
    """
    lines = text.splitlines()
    entries: list[dict] = []
    for i, line in enumerate(lines):
        m = ROUTE_RE.match(line.strip())
        if m:
            entries.append({"line": i, "raw": line, "keywords": m.group("kw").split(),
                            "target": m.group("target")})
    first = entries[0]["line"] if entries else len(lines)
    lead = lines[:first]
    tail_start = entries[-1]["line"] + 1 if entries else first
    tail = lines[tail_start:]
    return lead, entries, tail


def validate_keywords(kws: list[str], where: str) -> list[str]:
    if not isinstance(kws, list) or not all(isinstance(k, str) for k in kws):
        raise PlanError(f"{where}: keywords must be a list of strings")
    kws = [k.strip() for k in kws if k.strip()]
    if not (MIN_KW <= len(kws) <= MAX_KW):
        raise PlanError(f"{where}: {len(kws)} keywords; must be {MIN_KW}-{MAX_KW}")
    for k in kws:
        if "," in k or ARROW in k or " " in k:
            raise PlanError(f"{where}: keyword {k!r} must be one token, no comma/arrow")
        if k != k.lower():
            raise PlanError(f"{where}: keyword {k!r} must be lowercase")
    if len(set(kws)) != len(kws):
        raise PlanError(f"{where}: duplicate keyword inside the table")
    return kws


def load_plan(path: Path) -> dict:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PlanError(f"cannot read plan: {exc}") from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("domains"), list):
        raise PlanError("plan must be an object with a 'domains' list")
    return plan


def check_plan(plan: dict, store: Path) -> tuple[list[dict], list[dict]]:
    """Validate the plan against the store. Returns (domains, index entries)."""
    index_path = store / "MEMORY.md"
    if not index_path.exists():
        raise PlanError(f"no MEMORY.md in {store}")
    _lead, entries, _tail = split_index(index_path.read_text(encoding="utf-8"))
    by_target: dict[str, dict] = {}
    for e in entries:
        if e["target"] in by_target:
            raise PlanError(f"index already has two lines for {e['target']}")
        by_target[e["target"]] = e

    seen_children: dict[str, str] = {}
    seen_synapses: set[str] = set()
    domains = []
    for i, d in enumerate(plan["domains"]):
        where = f"domain[{i}]"
        if not isinstance(d, dict):
            raise PlanError(f"{where}: must be an object")
        synapse = str(d.get("synapse") or "").strip()
        if not NAME_RE.match(synapse):
            raise PlanError(f"{where}: synapse must be a bare *.md filename, got {synapse!r}")
        if synapse in seen_synapses:
            raise PlanError(f"{where}: synapse {synapse} declared twice")
        if (store / synapse).exists():
            raise PlanError(f"{where}: {synapse} already exists in the store")
        seen_synapses.add(synapse)
        kws = validate_keywords(d.get("keywords") or [], f"{where}.keywords")
        children = d.get("children") or []
        if not isinstance(children, list) or len(children) < 2:
            raise PlanError(f"{where}: a synapse needs at least 2 children (one route is a wasted hop)")
        child_map = {}
        for child in children:
            child = str(child)
            if child not in by_target:
                raise PlanError(f"{where}: {child} has no index line in this store")
            if child in seen_children:
                raise PlanError(f"{where}: {child} is already in domain {seen_children[child]}")
            if not (store / child).exists():
                raise PlanError(f"{where}: {child} is indexed but missing on disk")
            seen_children[child] = synapse
            child_map[child] = by_target[child]["keywords"]
        overrides = d.get("child_keywords") or {}
        if not isinstance(overrides, dict):
            raise PlanError(f"{where}.child_keywords must be an object")
        for child, child_kws in overrides.items():
            if child not in child_map:
                raise PlanError(f"{where}.child_keywords: {child} is not a child of {synapse}")
            child_map[child] = validate_keywords(list(child_kws), f"{where}.child_keywords[{child}]")
        used: dict[str, str] = {}
        for child, child_kws in child_map.items():
            for k in child_kws:
                if k in used and used[k] != child:
                    raise PlanError(
                        f"{where}: keyword {k!r} is on both {used[k]} and {child} — keywords must be "
                        f"unique within one synapse. Give it to one child, or put it on the "
                        f"synapse's own index line instead.")
                used[k] = child
        domains.append({"synapse": synapse, "keywords": kws, "children": children,
                        "child_keywords": child_map, "rationale": str(d.get("rationale") or "")})
    return domains, entries


def render(domains: list[dict], entries: list[dict], lead: list[str], tail: list[str]) -> tuple[str, dict]:
    """Build the new MEMORY.md and the synapse files in memory."""
    domain_by_child = {c: d for d in domains for c in d["children"]}
    first_line = {}
    for d in domains:
        first_line[d["synapse"]] = min(e["line"] for e in entries if e["target"] in d["children"])
    lines: list[str] = list(lead)
    moves = []
    for e in entries:
        d = domain_by_child.get(e["target"])
        if d is None:
            lines.append(e["raw"].rstrip())
            continue
        if first_line[d["synapse"]] == e["line"]:
            lines.append(" ".join(d["keywords"]) + f" {ARROW} {d['synapse']}")
            moves.append({"old_index_line": e["raw"], "new_index_line": lines[-1],
                          "children": d["children"]})
    lines.extend(tail)
    index_text = "\n".join(lines).rstrip() + "\n"
    synapses = {}
    for d in domains:
        body = [f"# {Path(d['synapse']).stem.replace('-', ' ').title()}"]
        body.append("")
        for child in d["children"]:
            body.append(" ".join(d["child_keywords"][child]) + f" {ARROW} {child}")
        synapses[d["synapse"]] = "\n".join(body).rstrip() + "\n"
    return index_text, synapses


def reachable(store_text: dict[str, str], start: str = "MEMORY.md") -> set[str]:
    """All files reachable from the index, following route lines."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        for line in store_text.get(name, "").splitlines():
            m = ROUTE_RE.match(line.strip())
            if m and m.group("target") not in seen:
                stack.append(m.group("target"))
    return seen


def run_verify(store: Path) -> tuple[int, str]:
    verify = Path(__file__).with_name("verify_index.py")
    r = subprocess.run([sys.executable, str(verify), str(store / "MEMORY.md"),
                        "--memdir", str(store), "--tree", "--keywords"],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def stage(store: Path, plan: dict) -> tuple[Path, dict, dict]:
    """Build the post-migration store in a temp dir and run both gates."""
    domains, entries = check_plan(plan, store)
    lead, entries2, tail = split_index((store / "MEMORY.md").read_text(encoding="utf-8"))
    assert entries == entries2
    index_text, synapses = render(domains, entries, lead, tail)

    before = {p.name: p.read_text(encoding="utf-8", errors="replace")
              for p in store.glob("*.md") if p.is_file()}
    after = dict(before)
    after["MEMORY.md"] = index_text
    after.update(synapses)

    old_reach = reachable(before)
    new_reach = reachable(after)
    lost = sorted(old_reach - new_reach)
    if lost:
        raise PlanError(f"reachability gate: {len(lost)} memories would be orphaned: {lost[:5]}")

    tmp = Path(tempfile.mkdtemp(prefix="dynmem-migrate-"))
    for p in store.iterdir():
        if p.is_file() and (p.suffix == ".md"):
            (tmp / p.name).write_text(before.get(p.name, p.read_text(encoding="utf-8", errors="replace")),
                                      encoding="utf-8")
    (tmp / "MEMORY.md").write_text(index_text, encoding="utf-8")
    for name, text in synapses.items():
        (tmp / name).write_text(text, encoding="utf-8")

    code, out = run_verify(tmp)
    if code != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise PlanError("validator gate failed on the staged store:\n" + out[-1500:])
    return tmp, {"index_text": index_text, "synapses": synapses}, {"entries": entries, "domains": domains}


def do_apply(store: Path, plan: dict) -> int:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    a = store.parent / "memories-backup" / run_id
    b = migration_root() / run_id
    b.mkdir(parents=True, exist_ok=True)
    a.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(store, a)
    (a / "files").mkdir(exist_ok=True)
    shutil.copy2(store / "MEMORY.md", a / "files" / "MEMORY.md.orig")
    files_before = {p.name: sha256(p) for p in store.glob("*.md")}
    with tarfile.open(b / "store.tar.gz", "w:gz") as tf:
        tf.add(store, arcname="memories")
    (b / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    staged, rendered, checked = stage(store, plan)
    try:
        # publish: synapse files first, index last (a crash mid-way leaves the old index)
        for name, text in rendered["synapses"].items():
            (store / name).write_text(text, encoding="utf-8")
        (store / "MEMORY.md").write_text(rendered["index_text"], encoding="utf-8")
    finally:
        shutil.rmtree(staged, ignore_errors=True)

    manifest = {
        "run_id": run_id, "store": str(store), "applied_at": int(time.time()),
        "backup": str(a), "plan": str(b / "plan.json"),
        "files_before": files_before,
        "files_after": {p.name: sha256(p) for p in store.glob("*.md")},
        "index_before": (a / "files" / "MEMORY.md.orig").read_text(encoding="utf-8"),
        "index_after": rendered["index_text"],
        "created": sorted(rendered["synapses"]),
        "moves": [{"child": c, "to_synapse": d["synapse"], "keywords": d["child_keywords"][c]}
                  for d in checked["domains"] for c in d["children"]],
    }
    (b / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    code, out = run_verify(store)
    print(f"applied; backup {a} (second copy {b})")
    print(f"validator exit: {code}")
    if code != 0:
        print(out[-1200:], file=sys.stderr)
        print(f"validator failed after publish — restore with: migrate.py --undo {a}", file=sys.stderr)
        return 1
    for line in out.splitlines():
        if line.startswith(("tree:", "keywords:", "lines:", "  [FAIL]")):
            print(line)
    return 0


def do_undo(run_dir: Path, force: bool = False) -> int:
    run_dir = run_dir.resolve()
    manifest_path = migration_root() / run_dir.name / "manifest.json"
    if not run_dir.exists() or not manifest_path.exists():
        print(f"no such run: {run_dir}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    store = Path(manifest["store"])
    expected = {p.name: sha256(p) for p in store.glob("*.md")}
    if not force and expected != manifest.get("files_after"):
        print("store changed since the run; refusing to overwrite (use --force)", file=sys.stderr)
        return 1
    for p in store.glob("*.md"):
        p.unlink()
    for p in run_dir.glob("*"):
        if p.is_file():
            shutil.copy2(p, store / p.name)
    code, out = run_verify(store)
    print(f"restored {store} from {run_dir}; validator exit: {code}")
    return code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", default=str(default_store()))
    ap.add_argument("--plan")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", metavar="RUN_DIR")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--runs", action="store_true")
    args = ap.parse_args(argv)
    store = Path(args.store).expanduser()

    if args.runs:
        base = migration_root()
        for d in sorted(base.iterdir()) if base.exists() else []:
            print(d.name)
        return 0
    if args.undo:
        return do_undo(Path(args.undo), force=args.force)
    if not args.plan:
        ap.error("--plan is required (or use --undo / --runs)")
    plan = load_plan(Path(args.plan))
    try:
        domains, entries = check_plan(plan, store)
        covered = {c for d in domains for c in d["children"]}
        print(f"store: {store}")
        print(f"index lines: {len(entries)} -> {len(entries) - len(covered) + len(domains)}"
              f" ({len(domains)} synapses covering {len(covered)} memories)")
        for d in domains:
            print(f"  {d['synapse']:32s} {len(d['children'])} children  "
                  f"kw={','.join(d['keywords'][:5])}{'…' if len(d['keywords']) > 5 else ''}")
            for c in d["children"]:
                print(f"      - {c}")
        if not args.apply:
            print("dry run: nothing written (use --apply)")
            return 0
    except PlanError as exc:
        print(f"plan rejected: {exc}", file=sys.stderr)
        return 2
    try:
        return do_apply(store, plan)
    except PlanError as exc:
        print(f"aborted: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
