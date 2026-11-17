#!/usr/bin/env python3
"""Daily dynmem behaviour report — store health, routing evidence, guard activity.

Stdlib only, no network, no LLM. Designed to run as a no_agent cron job: whatever
it prints is delivered verbatim. Profile-aware through $HERMES_HOME.

  python3 dynmem_daily_report.py            # report for the last 24h
  python3 dynmem_daily_report.py --hours 48
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ARROW = "\u2192"
ROUTE = re.compile(r"^(?P<kw>\S.*?)\s*\u2192\s*(?P<t>[A-Za-z0-9_.\-]+\.md)\s*$")


def home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def memdir() -> Path:
    return home() / "memories"


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def route_lines(text: str) -> list[tuple[list[str], str, str]]:
    """Real route lines only — the structural template line is not an entry."""
    out = []
    for line in text.splitlines():
        m = ROUTE.match(line.strip())
        if not m:
            continue
        kws = [k for k in re.split(r"[,\s]+", m.group("kw").strip()) if k]
        if kws == ["keyword", "keyword", "keyword"] and m.group("t") == "file.md":
            continue
        out.append((kws, m.group("t"), line.strip()))
    return out


def is_synapse(text: str) -> bool:
    body = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    return bool(body) and all(ROUTE.match(l) for l in body)


def store_health() -> dict:
    m = memdir()
    idx = read(m / "MEMORY.md")
    entries = route_lines(idx)
    files = {p.name: read(p) for p in m.glob("*.md")} if m.exists() else {}
    synapses = {f for f, t in files.items() if f != "MEMORY.md" and is_synapse(t)}

    targets = Counter(t for _, t, _ in entries)
    duplicates = sorted(t for t, n in targets.items() if n > 1)
    dead = sorted(t for t in targets if t not in files)
    kw_owner: dict[str, str] = {}
    collisions = []
    for kws, t, _ in entries:
        for k in kws:
            if k in kw_owner and kw_owner[k] != t:
                collisions.append((k, kw_owner[k], t))
            kw_owner.setdefault(k, t)
    double = []
    for t in targets:
        for parent in sorted(synapses):
            if any(pt == t for _, pt, _ in route_lines(files[parent])):
                double.append((t, parent))
                break
    return {
        "index_lines": len(entries), "index_chars": len(idx), "files": len(files),
        "synapses": len(synapses), "duplicates": duplicates, "dead": dead,
        "collisions": collisions, "double": double,
    }


def validator_summary() -> dict:
    script = Path(__file__).with_name("verify_index.py")
    if not script.exists():
        return {}
    try:
        r = subprocess.run([sys.executable, str(script), str(memdir() / "MEMORY.md"),
                            "--memdir", str(memdir()), "--tree", "--keywords"],
                           capture_output=True, text=True, timeout=120)
    except Exception:
        return {}
    out = r.stdout + r.stderr
    def grab(pat: str) -> str:
        m = re.search(pat, out)
        return m.group(1) if m else "?"
    return {
        "exit": r.returncode,
        "ok": grab(r"(\d+) lines OK"), "bad": grab(r"(\d+) bad lines"),
        "orphans": grab(r"(\d+) orphaned files"),
        "collisions": grab(r"(\d+) tier collisions"),
        "tree": grab(r"(\d+) tree problems"),
        "tiers": grab(r"keywords: (.+)"),
    }


def memcheck_window(hours: float) -> dict:
    p = home() / "state" / "memcheck" / "samples.jsonl"
    cutoff = time.time() - hours * 3600
    recs = []
    for line in read(p).splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict) and float(d.get("ts") or 0) >= cutoff:
            recs.append(d)
    opened = Counter()
    for d in recs:
        for f in (d.get("opened") or "").split(",") if isinstance(d.get("opened"), str) else (d.get("opened") or []):
            f = str(f).strip()
            if f and f != "null":
                opened[f] += 1
    return {
        "turns": len(recs),
        "wrong": sum(1 for d in recs if str(d.get("wrong") or "").strip().lower() in {"true", "yes", "1"}),
        "problems": sum(len(d.get("problems") or []) for d in recs),
        "top_opened": opened.most_common(5),
        "file_bytes": p.stat().st_size if p.exists() else 0,
        "rotated": (p.parent / "samples.jsonl.1").exists(),
    }


def guard_activity(hours: float) -> dict:
    cutoff = time.time() - hours * 3600
    logs = sorted((home() / "logs").glob("agent.log*")) if (home() / "logs").exists() else []
    refusals = Counter()
    calls = 0
    stamp = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")
    for lg in logs:
        for line in read(lg).splitlines():
            if "[dynmem]" not in line:
                continue
            m = stamp.match(line)
            if m:
                try:
                    ts = time.mktime(time.strptime(m.group(1).replace("T", " "), "%Y-%m-%d %H:%M:%S"))
                except ValueError:
                    ts = 0
                if ts and ts < cutoff:
                    continue
            if "memory() call" in line:
                calls += 1
            low = line.lower()
            if "refused" in low or "blocked" in low or "wrong arrow" in low or "malformed" in low:
                key = "duplicate/target" if "already has an index line" in low else \
                      "keyword taken" if "already routes to" in low else \
                      "missing target" if "does not exist" in low else \
                      "double-homed" if "already a child" in low else \
                      "write-vector" if "write-locked" in low or "write vector" in low else \
                      "format" if "malformed" in low or "arrow" in low or "keywords" in low else "other"
                refusals[key] += 1
    return {"calls": calls, "refusals": sum(refusals.values()), "by_reason": refusals.most_common(6)}


def config_bits() -> dict:
    text = read(home() / "config.yaml")
    block = re.search(r"^\s{4}dynmem:\s*\n((?:\s{6,}.*\n|\s*\n)*)", text, re.M)
    body = block.group(1) if block else ""
    prof = re.search(r"^\s*profile:\s*(\S+)", body, re.M)
    mem = re.search(r"memcheck:\s*\n\s*enabled:\s*(\S+)", body)
    ver = re.search(r"^version:\s*[\"']?([0-9.]+)", read(home() / "plugins" / "dynmem" / "plugin.yaml"), re.M)
    return {"profile": prof.group(1) if prof else "(unset)",
            "memcheck": mem.group(1) if mem else "(unset)",
            "installed_version": ver.group(1) if ver else "(not installed)"}


def cron_states() -> list[str]:
    p = home() / "cron" / "jobs.json"
    try:
        data = json.loads(read(p))
    except Exception:
        return []
    jobs = data.get("jobs", data) if isinstance(data, dict) else data
    out = []
    for j in jobs if isinstance(jobs, list) else []:
        name = str(j.get("name") or "")
        if not re.search(r"dynmem|memory", name, re.I):
            continue
        state = "paused" if j.get("paused") or j.get("enabled") is False else "active"
        out.append(f"{name}: {state}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24.0)
    args = ap.parse_args(argv)

    h = store_health()
    v = validator_summary()
    mc = memcheck_window(args.hours)
    g = guard_activity(args.hours)
    c = config_bits()

    state_path = home() / "state" / "dynmem" / "report-state.json"
    prev = {}
    try:
        prev = json.loads(read(state_path))
    except Exception:
        pass
    now = {"index_lines": h["index_lines"], "index_chars": h["index_chars"],
           "collisions": len(h["collisions"]), "bad": v.get("bad"), "files": h["files"]}

    def delta(key):
        a, b = prev.get(key), now.get(key)
        if not isinstance(a, int) or not isinstance(b, int):
            return ""
        d = b - a
        return f" ({d:+d})" if d else " (unchanged)"

    L = []
    L.append(f"dynmem daily — {time.strftime('%Y-%m-%d %H:%M')} · profile {home().name} · v{c['installed_version']}")
    L.append("")
    L.append(f"Store: {h['index_lines']} index lines{delta('index_lines')}, {h['index_chars']} chars{delta('index_chars')}, "
             f"{h['files']} files, {h['synapses']} synapses")
    if v:
        L.append(f"Validator: {v['ok']} OK / {v['bad']} bad{delta('bad')}, {v['collisions']} collisions{delta('collisions')}, "
                 f"{v['tree']} tree problems, {v['orphans']} orphans (exit {v['exit']})")
        L.append(f"Shape: {v['tiers']}")
    if h["duplicates"]:
        L.append(f"Duplicate targets ({len(h['duplicates'])}): " + ", ".join(h["duplicates"][:5]))
    if h["dead"]:
        L.append(f"Dead targets ({len(h['dead'])}): " + ", ".join(h["dead"][:5]))
    if h["double"]:
        L.append(f"Double-homed ({len(h['double'])}): " + ", ".join(f"{t} under {p}" for t, p in h["double"][:4]))
    if h["collisions"]:
        L.append(f"Index keyword clashes ({len(h['collisions'])} pairs): " +
                 ", ".join(f"{k} ({a} vs {b})" for k, a, b in h["collisions"][:4]))
    L.append("")
    L.append(f"Routing evidence, last {args.hours:g}h (memcheck {c['memcheck']}): {mc['turns']} turns checked, "
             f"{mc['wrong']} flagged wrong, {mc['problems']} problems")
    if mc["top_opened"]:
        L.append("Most opened: " + ", ".join(f"{f} ×{n}" for f, n in mc["top_opened"]))
    L.append(f"Samples: {mc['file_bytes']/1024:.0f} KiB" + (" (rotated window present)" if mc["rotated"] else ""))
    L.append("")
    L.append(f"Guard, last {args.hours:g}h: {g['calls']} memory calls, {g['refusals']} refusals")
    if g["by_reason"]:
        L.append("Refusals by reason: " + ", ".join(f"{k} ×{n}" for k, n in g["by_reason"]))
    L.append(f"Config: profile={c['profile']}, memcheck={c['memcheck']}")
    cs = cron_states()
    if cs:
        L.append("Crons: " + "; ".join(cs))
    if not prev:
        L.append("(first run — deltas start tomorrow)")

    print("\n".join(L))
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(now, indent=2), encoding="utf-8")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
