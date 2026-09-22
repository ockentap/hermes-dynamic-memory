#!/usr/bin/env python3
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
# See the NOTICE file for attribution requirements.
"""dynmem-watchdog.py — access-tally + archival prune for the dynamic-memory index.

Run daily via cron (no_agent). Silent when nothing needs saying.

Pipeline, each run:
  1. TALLY.    Scan new assistant tool_call rows in ~/.hermes/state.db
               (incrementally, by rowid watermark) and count every argument
               reference to a topic file under ~/.hermes/memories/ as one
               "access" of that file. Counts merge into the sidecar
               memories/.access-tally.json — the index itself is never
               annotated with counters.
  2. ORDER.    Untagged index lines are sorted by access desc, tie-break
               last-access desc, tie-break stable. !! and ! tagged lines never
               move. Sorting only permutes untagged lines among the slots they
               already occupy; header, blank lines, and any non-entry lines are
               frozen anchors.
  3. ARCHIVE.  If the index content exceeds the soft cap (95% of
               memory.memory_char_limit), evict from the bottom — the
               LEAST-accessed untagged entries — until the index is back under
               the hard target (80%). NOTHING IS DELETED: the topic file moves
               to memories/archived memories/<name>.md (plain .md, collision-
               suffixed if needed) and its index line is added to
               memories/archived memories/archived-memories.md — a searchable
               keyword index of the same shape as the live one, rebuilt from
               the files on disk each run. A full backup of the index is
               written to that same dir before any rewrite.

Never-archived, in every mode:
  * lines tagged ! or !!
  * topic files younger than WATCHDOG_GRACE_DAYS (default 14)
  * topic files accessed within the grace window
  * the literal template line and everything in the header

Usage:
  dynmem-watchdog.py                # apply
  dynmem-watchdog.py --dry-run      # report only, touch nothing
  dynmem-watchdog.py --report       # print a top/bottom status card and exit
  WATCHDOG_GRACE_DAYS=30 ...        # grace window override
  WATCHDOG_HERMES_HOME=/path ...    # test against a different hermes home

Watchdog delivery contract (no_agent cron):
  empty stdout + exit 0  -> silent
  message on stdout      -> delivered verbatim to the user
  non-zero exit          -> scheduler alerts "watchdog is broken"
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

GRACE_DAYS = int(os.environ.get("WATCHDOG_GRACE_DAYS", "14"))
SOFT_CAP_FRAC = float(os.environ.get("WATCHDOG_SOFT_CAP_FRAC", "0.95"))
HARD_TARGET_FRAC = float(os.environ.get("WATCHDOG_HARD_TARGET_FRAC", "0.80"))
DEFAULT_CAP = 2200                       # matches Hermes' memory_char_limit default
WARN_COOLDOWN_DAYS = 7
TEMPLATE_PREFIX = "keyword,keyword,keyword"
NAME_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]{1,80})\.md")
# Index line: optional qualifier, keyword list, unicode arrow, bare .md target.
ENTRY_RE = re.compile(r"^(?:(!!|!)\s*)?([^→]+?)\s*→\s*([A-Za-z0-9][A-Za-z0-9._-]*\.md)\s*$")
SECTION_RE = re.compile(r"^\s*\u00a7\s*$")


# ------------------------------------------------------------- paths ------

class Paths:
    def __init__(self, home: Path):
        self.mem = home / "memories"
        self.index = self.mem / "MEMORY.md"
        self.db = home / "state.db"
        self.config = home / "config.yaml"
        self.tally = self.mem / ".access-tally.json"
        self.arch_dir = self.mem / "archived memories"
        self.arch_index = self.arch_dir / "archived-memories.md"
        self.log = home / "logs" / "dynmem-watchdog.log"


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def log_line(paths, msg):
    try:
        paths.log.parent.mkdir(parents=True, exist_ok=True)
        with open(paths.log, "a") as f:
            f.write(f"{iso()} {msg}\n")
    except OSError:
        pass


def atomic_write(path: Path, text: str):
    tmp = path.parent / (path.name + ".wd-tmp")
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def read_char_cap(paths):
    """memory.memory_char_limit from config.yaml, Hermes default if absent."""
    try:
        m = re.search(r"memory_char_limit:\s*(\d+)", paths.config.read_text())
        if m:
            return int(m.group(1))
    except OSError:
        pass
    return DEFAULT_CAP


# -------------------------------------------------------------- tally -----

def load_tally(paths):
    doc = {"_meta": {"last_rowid": 0}, "files": {}}
    if paths.tally.exists():
        try:
            raw = json.loads(paths.tally.read_text())
        except (json.JSONDecodeError, OSError):
            log_line(paths, "warn: tally unreadable — starting fresh")
            return doc
        if isinstance(raw, dict):
            if "files" in raw and isinstance(raw.get("files"), dict):
                doc = {"_meta": raw.get("_meta", {}) or {"last_rowid": 0},
                       "files": raw["files"]}
            else:  # legacy shape: plain {file: {...}} map
                doc = {"_meta": {"last_rowid": 0}, "files": raw}
    doc["_meta"].setdefault("last_rowid", 0)
    return doc


def topic_names(paths):
    """Set of *.md topic-file names recognised as tally targets."""
    names = set()
    for pattern_dir in (paths.mem, paths.arch_dir):
        if pattern_dir.is_dir():
            for p in pattern_dir.iterdir():
                if p.is_file() and ".md" in p.name:
                    # USER.md.bak.* etc. — count only real topic basenames
                    base = re.split(r"\.archived-|\.bak", p.name)[0]
                    if base.endswith(".md"):
                        names.add(base)
    names.discard(paths.index.name)
    names.discard("USER.md")
    names.discard("archived-memories.md")
    return names


def scan_access(paths, last_rowid, known):
    """Count topic-file mentions in new tool_call rows.

    Returns ({name: (reads, last_iso)}, max_rowid_seen). One message counts at
    most once per file (a single agent turn issuing 5 reads of one file is one
    access event, not five).
    """
    if not paths.db.exists():
        raise RuntimeError(f"state.db not found: {paths.db}")
    conn = sqlite3.connect(f"file:{paths.db}?mode=ro", uri=True, timeout=10)
    try:
        rows = conn.execute(
            "SELECT id, tool_calls, timestamp FROM messages "
            "WHERE id > ? AND tool_calls IS NOT NULL AND tool_calls NOT IN ('', '[]') "
            "ORDER BY id",
            (last_rowid,),
        ).fetchall()
    finally:
        conn.close()

    hits = {}
    max_id = last_rowid
    for rid, tc, ts in rows:
        max_id = max(max_id, rid)
        try:
            calls = json.loads(tc)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(calls, dict):
            calls = [calls]
        if not isinstance(calls, list):
            continue
        mentioned = set()
        for c in calls:
            if not isinstance(c, dict):
                continue
            args = c.get("args")
            if args is None:
                fn = c.get("function") or {}
                args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = None
            if isinstance(args, dict):
                try:
                    blob = json.dumps(args, ensure_ascii=False)
                except (TypeError, ValueError):
                    continue
            elif isinstance(args, str):
                blob = args
            else:
                continue
            for m in NAME_RE.finditer(blob):
                name = m.group(1) + ".md"
                if name in known:
                    mentioned.add(name)
        dt = datetime.fromtimestamp(float(ts or 0), tz=timezone.utc)
        stamp = iso(dt)
        for name in mentioned:
            e = hits.setdefault(name, [0, ""])
            e[0] += 1
            if stamp > e[1]:
                e[1] = stamp
    return {k: tuple(v) for k, v in hits.items()}, max_id


def merge_hits(files, hits):
    touched = 0
    for name, (reads, last) in hits.items():
        ent = files.setdefault(name, {"reads": 0, "last": ""})
        ent["reads"] = int(ent.get("reads", 0)) + reads
        if last > ent.get("last", ""):
            ent["last"] = last
        touched += 1
    return touched


# -------------------------------------------------------------- index -----

def parse_index(text):
    """-> (lines, body_start, {pos: entry}) for the live index file text.

    body_start is one past the LAST template line (the template line marks the
    end of the header block). An entry dict is {tag, target, raw, pos}; every
    other body line is a frozen anchor.
    """
    lines = text.split("\n")
    boundary = None
    for i, l in enumerate(lines):
        if l.strip().startswith(TEMPLATE_PREFIX):
            boundary = i
    if boundary is None:
        raise RuntimeError(
            "no template line found — refusing to guess where the header ends")
    body_start = boundary + 1
    entries = {}
    for i in range(body_start, len(lines)):
        if SECTION_RE.match(lines[i]):
            continue
        m = ENTRY_RE.match(lines[i].strip())
        if not m:
            continue
        if lines[i].strip().startswith(TEMPLATE_PREFIX):
            continue  # the template example line must never move
        target = m.group(3)
        if target == "file.md":
            continue  # placeholder target = header template, frozen
        entries[i] = {"tag": m.group(1) or "", "target": target,
                      "raw": lines[i], "pos": i}
    return lines, body_start, entries


def access_of(entry, files):
    t = files.get(entry["target"], {})
    if not isinstance(t, dict):
        t = {}
    return int(t.get("reads", 0)), (t.get("last") or "")


def content_chars(lines, body_start):
    """Char count the way Hermes' memory store counts it: non-empty lines
    after the header joined by newline. Header prose does not count."""
    body = [l for l in lines[body_start:] if l.strip() and not SECTION_RE.match(l)]
    return len("\n".join(body))


def compute_order(lines, body_start, entries, files):
    """Permutes untagged entry lines among their own slots, hot first.
    Returns (new_lines, n_slots, n_moved)."""
    slots = sorted(pos for pos, e in entries.items() if not e["tag"])
    if not slots:
        return lines, 0, 0
    ranked = [entries[p] for p in slots]    # seeded in position order (stable)
    ranked.sort(key=lambda e: access_of(e, files)[1], reverse=True)
    ranked.sort(key=lambda e: access_of(e, files)[0], reverse=True)
    out = list(lines)
    moved = 0
    for pos, e in zip(slots, ranked):
        out[pos] = e["raw"]
        if pos != e["pos"]:
            moved += 1
    return out, len(slots), moved


# ------------------------------------------------------------ archive -----

ARCH_HEADER_TMPL = """# Archived Memories — {here}
#
# Keyword index for memory topic files pruned from the live {mem} index.
# Archiving is eviction from the HOT index, NOT deletion: every file here is
# complete and readable, and each line below is the exact index entry that
# was removed from {fname}. Search this file the same way you search the live
# index — it is a normal keyword table, one step above any deep archive in
# the retrieval order.
#
# Rules the archiver enforces: pinned (!) and critical (!!) entries are
# never archived, and files younger than {grace} days are never archived.
#
# Index backups taken before each prune run live in this directory as
# `{fname}.bak-<timestamp>`. To restore an entry: move `{arch}/NAME.md` back
# into `{mem}/` and re-add its line via the memory tool — the line below is
# verbatim what to re-add. Eviction stats (reads, dates) live in the
# sidecar `.access-tally.json`, not in the lines here.
#
## Archive index

"""


def unique_arch_name(paths, target):
    """Collision-safe name inside the archive dir: X.md, X-2.md, X-3.md..."""
    if not (paths.arch_dir / target).exists():
        return target
    stem, dot, ext = target.rpartition(".md")
    n = 2
    while (paths.arch_dir / f"{stem}-{n}.md").exists():
        n += 1
    return f"{stem}-{n}.md"


def archive_step(paths, lines, body_start, entries, files, cap, dry=False):
    """Evict bottom entries while content is above the soft cap, down to the
    hard target. Returns (new_text, archived:[(orig_target, arch_name, raw,
    reads, last)], still_over:bool). In dry mode nothing is moved or mutated
    on disk."""
    soft = SOFT_CAP_FRAC * cap
    hard = HARD_TARGET_FRAC * cap
    if content_chars(lines, body_start) <= soft:
        return "\n".join(lines), [], False

    _, _, entries2 = parse_index("\n".join(lines))
    untagged = sorted((e for e in entries2.values() if not e["tag"]),
                      key=lambda e: (e["pos"]))
    # eviction order: bottom of the hot-sorted layout = least access, oldest
    cutoff = utcnow() - timedelta(days=GRACE_DAYS)
    candidates = []
    for e in sorted(untagged,
                    key=lambda e: (access_of(e, files)[1], access_of(e, files)[0])):
        src = paths.mem / e["target"]
        if not src.exists():
            continue                          # broken pointer: integrity job
        try:
            mtime = datetime.fromtimestamp(src.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime > cutoff:
            continue                          # too young to judge
        reads, last = access_of(e, files)
        last_dt = parse_iso(last)
        if last_dt and last_dt > cutoff:
            continue                          # accessed recently
        candidates.append(e)

    cur = list(lines)
    keep = [True] * len(cur)
    archived = []
    size = content_chars(cur, body_start)
    for e in candidates:
        if size <= hard:
            break
        src = paths.mem / e["target"]
        reads, last = access_of(e, files)
        if dry:
            keep[e["pos"]] = False
            size -= len(e["raw"]) + 1
            archived.append((e["target"], e["target"], e["raw"], reads, last))
            continue
        dst_name = unique_arch_name(paths, e["target"])
        try:
            shutil.move(str(src), str(paths.arch_dir / dst_name))
        except OSError as exc:
            log_line(paths, f"warn: move failed for {e['target']}: {exc}")
            continue
        ent = files.setdefault(e["target"], {})
        ent["archived"] = iso()
        ent["archived_as"] = dst_name
        keep[e["pos"]] = False
        size -= len(e["raw"]) + 1
        archived.append((e["target"], dst_name, e["raw"], reads, last))

    cur = [l for i, l in enumerate(cur) if keep[i]]
    over = content_chars(cur, body_start) > soft
    return "\n".join(cur), archived, over


def write_archive_log(paths, archived):
    """Regenerate archived-memories.md deterministically: a fixed comment
    header plus one BARE keyword line per topic file present in the archive
    dir. Archived entries use their original index line verbatim (so an
    archive line is a drop-in re-add), older lines carry forward. Lines stay
    bare — no trailing comments — so the archive validates with the same
    verify_index.py as the live index. Because the file is rebuilt from what
    is actually on disk it can never drift from the archive contents."""
    paths.arch_dir.mkdir(parents=True, exist_ok=True)
    header = ARCH_HEADER_TMPL.format(
        here=paths.arch_index, mem=paths.mem.name, fname=paths.index.name,
        arch=paths.arch_dir.name, grace=GRACE_DAYS)
    target_re = re.compile(r"→\s*([A-Za-z0-9][A-Za-z0-9._-]*\.md)\s*$")
    kept = {}
    if paths.arch_index.exists():
        try:
            body = paths.arch_index.read_text().split("## Archive index", 1)[-1]
            for l in body.split("\n"):
                m = target_re.search(l.strip())
                if m:
                    kept[m.group(1)] = l.strip()
        except OSError:
            pass
    for target, dst_name, raw, reads, last in archived:
        kept[dst_name] = raw.strip()
    names = sorted(p.name for p in paths.arch_dir.glob("*.md")
                   if p.name != paths.arch_index.name
                   and not p.name.startswith(paths.index.name + ".bak"))
    lines = [header]
    for name in names:
        if name in kept:
            lines.append(kept[name])
        else:
            parts = [w for w in name[:-3].split("-") if w][:4]
            kw = ",".join(parts + ["archived"] if len(parts) >= 4
                          else parts + ["archived", "memory", "pruned", "topic"])
            lines.append(f"{kw} → {name}")
    atomic_write(paths.arch_index, "\n".join(lines).rstrip() + "\n")


# -------------------------------------------------------------- modes -----

def status_report(paths, files, entries, cap, size):
    untagged = [e for e in entries.values() if not e["tag"]]
    tagged = [e for e in entries.values() if e["tag"]]
    ranked = sorted(untagged, key=lambda e: access_of(e, files), reverse=True)
    lines = [f"index: {size}/{cap} chars ({100.0*size/max(cap,1):.0f}%) — "
             f"soft {int(SOFT_CAP_FRAC*cap)}, prune-to {int(HARD_TARGET_FRAC*cap)}",
             f"entries: {len(entries)} ({len(tagged)} tagged, {len(untagged)} untagged)",
             "", "top 5 untagged:"]
    for e in ranked[:5]:
        r, l = access_of(e, files)
        lines.append(f"  {r:>4}  {l:<20}  {e['target']}")
    lines.append("bottom 5 (prune order unless in grace):")
    for e in list(ranked)[-5:]:
        r, l = access_of(e, files)
        lines.append(f"  {r:>4}  {l:<20}  {e['target']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--home", default=os.environ.get("WATCHDOG_HERMES_HOME",
                        str(Path.home() / ".hermes")))
    args = ap.parse_args()

    paths = Paths(Path(os.path.expanduser(args.home)).resolve())
    if not paths.index.exists():
        print(f"ERROR: index not found at {paths.index}", file=sys.stderr)
        return 3

    doc = load_tally(paths)
    files = doc["files"]
    cap = read_char_cap(paths)

    text = paths.index.read_text()
    lines, body_start, entries = parse_index(text)

    if args.report:
        print(status_report(paths, files, entries, cap, content_chars(lines, body_start)))
        return 0

    # 1. tally new accesses
    known = topic_names(paths)
    last_rowid = int(doc["_meta"].get("last_rowid", 0))
    try:
        hits, max_id = scan_access(paths, last_rowid, known)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    merge_hits(files, hits)
    doc["_meta"]["last_rowid"] = max_id
    doc["_meta"]["updated"] = iso()

    # 2. reorder
    new_lines, n_slots, n_moved = compute_order(lines, body_start, entries, files)

    # 3. archive if needed
    if not args.dry_run:
        paths.arch_dir.mkdir(parents=True, exist_ok=True)
    new_text, archived, still_over = archive_step(
        paths, new_lines, body_start, entries, files, cap, dry=args.dry_run)

    if args.dry_run:
        pre = content_chars(lines, body_start)
        post = content_chars(new_text.split("\n"), body_start)
        print(f"DRY-RUN: {len(hits)} files with new reads (rows>{last_rowid}); "
              f"{n_moved}/{n_slots} untagged lines would move; size {pre} -> {post} "
              f"of {cap}")
        if archived:
            print("WOULD ARCHIVE (least-accessed, grace-checked):")
            for t, _dst, _raw, r, l in archived:
                print(f"  {t}  reads={r} last={l or 'never'}")
        else:
            print("would archive: nothing (under soft cap or all protected)")
        if still_over:
            print("WARNING: still above soft cap after pruning all eligible entries")
        return 0

    # 4. persist — order of writes matters: files first (done by archive_step),
    #    archive log, then index (with backup), then tally.
    #    The archive index rebuild is unconditional so a manually-restored
    #    file's line drops out even when nothing new is archived this run.
    write_archive_log(paths, archived)
    if new_text != text:
        shutil.copy2(paths.index,
                     paths.arch_dir / f"{paths.index.name}.bak-{utcnow().strftime('%Y%m%d-%H%M%S')}")
        if not new_text.endswith("\n"):
            new_text += "\n"
        atomic_write(paths.index, new_text)
    atomic_write(paths.tally, json.dumps(doc, indent=1))
    log_line(paths, f"rows>{last_rowid} hits={len(hits)} moved={n_moved} "
                    f"archived={len(archived)} size={content_chars(new_text.split(chr(10)), body_start)}/{cap}")

    # 5. user-visible output — empty means the cron stays silent
    if archived:
        names = ", ".join(t for t, *_ in archived)
        print(f"🧠 Memory watchdog: index passed {int(SOFT_CAP_FRAC*cap)}/{cap} chars — "
              f"archived {len(archived)} least-accessed entr"
              f"{'y' if len(archived)==1 else 'ies'} to 'archived memories/' "
              f"(nothing deleted): {names}")
        print(f"Restore anytime from {paths.arch_index} (original index lines "
              f"recorded there; index backup saved alongside).")
    if still_over:
        last_warn = parse_iso(doc["_meta"].get("last_cap_warn", ""))
        if not last_warn or utcnow() - last_warn > timedelta(days=WARN_COOLDOWN_DAYS):
            doc["_meta"]["last_cap_warn"] = iso()
            atomic_write(paths.tally, json.dumps(doc, indent=1))
            print(f"⚠️ Memory watchdog: index at "
                  f"{content_chars(new_text.split(chr(10)), body_start)}/{cap} chars "
                  f"but every remaining entry is pinned (!/!!) or inside the "
                  f"{GRACE_DAYS}-day grace window. Review manually or raise "
                  f"memory.memory_char_limit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
