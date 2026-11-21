#!/usr/bin/env python3
"""optimize — the idle memory optimiser behind the "🧠 Memory Optimized" hook.

Reads the new part of a session (or a transcript file), asks the model for
memwrite plans that capture every durable fact, applies them through memwrite,
and reports one line.

    python3 scripts/optimize.py --store ~/.hermes/memories --session <id>
    python3 scripts/optimize.py --store ~/.hermes/memories --transcript t.json
    python3 scripts/optimize.py ... --dry-run | --force | --quiet | --full-index

Watermarking: `~/.hermes/state/optimizer-watermark.json` holds, per session, the
id of the last message that was **successfully** written. Messages are processed
one at a time, so a failure stops the run at that message and the next trigger
resumes exactly there — already optimised messages are never re-summarised.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
MEMWRITE = HERE / "memwrite.py"
WATERMARK = pathlib.Path.home() / ".hermes" / "state" / "optimizer-watermark.json"
DEFAULT_STATE_DB = pathlib.Path.home() / ".hermes" / "state.db"


def resolve_state_db(store: pathlib.Path) -> pathlib.Path:
    """The state.db that owns this store.

    A profile store lives at <profile>/memories, so its database is the sibling
    <profile>/state.db — never the root ~/.hermes/state.db, which belongs to the
    default profile and has no rows for the sessions the gateway is writing.
    """
    candidate = store.parent / "state.db"
    if candidate.exists():
        return candidate
    return DEFAULT_STATE_DB


sys.path.insert(0, str(HERE))
import lookup  # noqa: E402  (shared provider + index helpers)

ARROW = "\u2192"
ROUTE_LINE = re.compile(r"^(?P<kw>.+?)\s*(?:\u2192|->)\s*(?P<t>[A-Za-z0-9_.\-]+\.md)\s*$")

SYSTEM = """You maintain a dynmem memory store: the index lists neurons, a neuron is
a table of route lines 'keyword keyword → child.md', and engrams are the terminal
memory files.

Read the transcript and write what must be remembered into the store.

The CANDIDATES block is a slice of the routing tree: index lines, then the
matched neurons' route lines, then their children as '<file> — <title>' (an
engram, with the title it already carries). Treat it as the existing store.

Rules:
- Capture EVERY durable fact, decision, identifier, path, number and correction.
  Keep identifiers verbatim (they are how the facts are checked later).
- Do not invent anything that is not in the transcript.
- Triage before writing: if a candidate engram's title covers the fact, mode
  "update" that file — do not create a near-duplicate. If a candidate NEURON
  covers the subject but no engram does, mode "new" with that neuron's existing
  name: its route lines merge, and add only the new engram(s).
- Create a new neuron only when no candidate line covers the subject. Never a
  sibling neuron for a topic that already has one.
- One subject per engram, 2-6 KB each; split a rich subject into aspect engrams.
  Never one giant engram. An engram shown near the 7 KB ceiling must NOT be
  extended: add a new aspect engram under the same neuron instead.
- An engram starts '# <title>', then 'Part of: <neuron>.md.', then the content.
- A neuron contains only route lines: 5-20 space-separated keywords, Unicode →,
  no commas.
- The index line points at the neuron. Its keywords must not repeat a keyword
  already used on another index line — pick the specific ones for this topic.
- Depth stays shallow: index → neuron → engram. Do not add a neuron whose child
  is another neuron unless the candidate tree already has that shape.
- If nothing covers the facts, mode "new" is correct.

Reply with JSON only:
{"plans":[
  {"mode":"new","neuron":{"name":"topic.md","lines":["kw kw → topic-aspect.md"]},
   "engrams":[{"name":"topic-aspect.md","content":"# ...\\nPart of: topic.md.\\n..."}],
   "index_line":"kw kw → topic.md"},
  {"mode":"update","target":"existing.md","content":"# ...\\nPart of: x.md.\\n..."}
]}"""


def load_watermark() -> dict:
    try:
        return json.loads(WATERMARK.read_text())
    except Exception:
        return {}


def save_watermark(data: dict) -> None:
    WATERMARK.parent.mkdir(parents=True, exist_ok=True)
    WATERMARK.write_text(json.dumps(data, indent=1))


def session_messages(db: pathlib.Path, session_id: str, after_id: int, limit: int = 60) -> list[dict]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute(
        "select id, role, content from messages where session_id=? and id>? and role in ('user','assistant')"
        " and content is not null order by id limit ?", (session_id, after_id, limit)).fetchall()
    return [{"id": r[0], "role": r[1], "content": r[2]} for r in rows]


def transcript_messages(path: str) -> list[dict]:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("messages", [])
    return [{"id": i, "role": m.get("role", "user"), "content": m.get("content", "")}
            for i, m in enumerate(data, 1)]


def _index_lines(store: pathlib.Path):
    out = []
    for line in (store / "MEMORY.md").read_text(encoding="utf-8").splitlines():
        if "→" not in line or line.lstrip().startswith("#"):
            continue
        kw, target = line.rsplit("→", 1)
        out.append((kw.split(), target.strip()))
    return out


def _route_body(path: pathlib.Path) -> list[str]:
    try:
        body = [l.strip() for l in path.read_text(encoding="utf-8", errors="replace").splitlines()
                if l.strip() and not l.strip().startswith("#")]
    except OSError:
        return []
    return [l for l in body if ARROW in l]


def _is_table(path: pathlib.Path) -> bool:
    """A neuron: at least half the non-comment body is route lines."""
    try:
        body = [l.strip() for l in path.read_text(encoding="utf-8", errors="replace").splitlines()
                if l.strip() and not l.strip().startswith("#")]
    except OSError:
        return False
    routes = [l for l in body if ARROW in l]
    return bool(routes) and len(routes) / max(1, len(body)) >= 0.5


def _title(path: pathlib.Path, limit: int = 72) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines()[:8]:
        if line.startswith("# "):
            return line[2:].strip()[:limit]
    first = next((l.strip() for l in text.splitlines() if l.strip()), "")
    return first[:limit]


def _expand(store: pathlib.Path, path: pathlib.Path, out: list[str],
            depth: int, indent: str, seen: set[str]) -> None:
    """Walk one branch of the routing tree, carrying descendant TITLES.

    The triage decision the optimiser has to make is update-vs-new at the
    engram level. Index lines and neuron route lines only name the children;
    two hops down without their titles the model is guessing, and a guess
    becomes a duplicate engram.
    """
    if depth <= 0 or path.name in seen or not path.exists():
        return
    seen.add(path.name)
    if _is_table(path):
        for route in _route_body(path)[:5]:
            out.append(indent + route)
            m = ROUTE_LINE.match(route)
            if m:
                _expand(store, store / m.group("t"), out, depth - 1, indent + "  ", seen)
    else:
        title = _title(path)
        try:
            kb = max(1, round(path.stat().st_size / 1024))
        except OSError:
            kb = 0
        if title:
            out.append(f"{indent}{path.name} — {title} ({kb} KB)")
        elif kb:
            out.append(f"{indent}{path.name} ({kb} KB)")


def candidate_block(store: pathlib.Path, text: str, limit: int = 12,
                    budget_chars: int = 5200, depth: int = 2) -> str:
    """The few index lines that could possibly matter, plus their descendants.

    IDF-weighted overlap, so a rare topical word outweighs a common one. When
    nothing scores, the block is empty and the prompt says a new topic is fine —
    cheaper and safer than shipping the whole index for every message.
    """
    lines = _index_lines(store)
    if not lines:
        return ""
    q = set(re.findall(r"[a-z0-9][a-z0-9_.\-/]{2,}", text.lower()))
    df: dict[str, int] = {}
    for kws, _ in lines:
        for kw in set(kws):
            df[kw] = df.get(kw, 0) + 1
    n = len(lines)
    scored = []
    for kws, target in lines:
        score = sum(math.log(1 + n / df.get(kw, 1)) for kw in set(kws) if kw in q)
        if score:
            scored.append((score, kws, target))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return ""
    out = []
    seen: set[str] = set()
    for _, kws, target in scored[:limit]:
        out.append(" ".join(kws[:8]) + " → " + target)
        _expand(store, store / target, out, depth, "    ", seen)
    block, size = [], 0
    for line in out:
        if size + len(line) > budget_chars:
            break
        block.append(line)
        size += len(line) + 1
    return "\n".join(block)


def compact_index(store: pathlib.Path, limit: int = 8) -> str:
    lines = []
    for line in (store / "MEMORY.md").read_text(encoding="utf-8").splitlines():
        if "→" not in line or line.lstrip().startswith("#"):
            continue
        kw, target = line.rsplit("→", 1)
        lines.append(" ".join(kw.split()[:limit]) + " → " + target.strip())
    return "\n".join(lines)


def extract_plans(text: str) -> list[dict]:
    """Tolerant JSON extraction: fences, surrounding prose, a bare plan object."""
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\s*|```$", "", t, flags=re.MULTILINE).strip()
    candidates = [t]
    if "{" in t and "}" in t:
        candidates.append(t[t.find("{"):t.rfind("}") + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
        except Exception:
            continue
        if isinstance(data, dict):
            if isinstance(data.get("plans"), list):
                return [p for p in data["plans"] if isinstance(p, dict)]
            if data.get("mode"):
                return [data]
        if isinstance(data, list):
            return [p for p in data if isinstance(p, dict)]
    return []


def index_keywords(store: pathlib.Path) -> set[str]:
    """Every keyword already on some index line — a new line may not repeat one."""
    try:
        text = (store / "MEMORY.md").read_text(encoding="utf-8")
    except OSError:
        return set()
    out: set[str] = set()
    for line in text.splitlines():
        m = ROUTE_LINE.match(line.strip())
        if m:
            out.update(m.group("kw").split())
    return out


def index_targets(store: pathlib.Path) -> set[str]:
    """Files that already own a top-level index line."""
    try:
        text = (store / "MEMORY.md").read_text(encoding="utf-8")
    except OSError:
        return set()
    return {m.group("t") for m in (ROUTE_LINE.match(l.strip()) for l in text.splitlines()) if m}


def repair_plan(plan: dict, extra_text: str = "", avoid_words=(), top_level=()) -> dict:
    """Normalise a model plan into the shape memwrite validates.

    Models emit index lines with commas, prose, or a missing arrow; memwrite
    rejects the whole plan over that one field, optimize counts it as a failure
    and the watermark never advances, so the same message is retried forever and
    nothing is ever saved. Repair the format instead of failing the plan.
    """
    plan = dict(plan)
    mode = str(plan.get("mode") or "new").strip().lower()
    plan["mode"] = mode if mode in {"new", "update"} else "new"

    if plan["mode"] == "update":
        target = str(plan.get("target") or "").strip()
        if target and target not in set(top_level):
            plan.pop("index_line", None)   # engram: already reachable via its neuron
            return plan

    def words(text: str) -> list[str]:
        text = text.replace("\u2192", " ").replace("->", " ")
        return [w for w in re.split(r"[,\s]+", text.strip()) if w]

    def pad(kw: str, target: str) -> str:
        """5-20 keywords that do not collide with a keyword already in the index."""
        avoid = set(avoid_words)
        have = [w for w in words(kw) if w not in avoid]
        if len(have) >= 5:
            return " ".join(have[:20])
        pool = words(target[:-3].replace("_", " ").replace("-", " "))
        pool += words(str((plan.get("engrams") or [{}])[0].get("content", ""))[:400]) \
            if plan.get("engrams") else []
        pool += words(extra_text[:600])
        for w in pool:
            w = w.lower().strip(".,;:()[]`'\"")
            if re.fullmatch(r"[a-z0-9][a-z0-9_.\-]{1,47}", w) and w not in avoid and w not in have:
                have.append(w)
            if len(have) >= 6:
                break
        return " ".join(have[:20])

    # neuron route lines: every line needs an arrow or memwrite aborts the plan
    if plan["mode"] == "new":
        neuron = dict(plan.get("neuron") or {})
        engrams = [e for e in (plan.get("engrams") or []) if isinstance(e, dict)]
        fallback_target = (engrams[0].get("name") if engrams else "") or ""
        lines = []
        for line in neuron.get("lines") or []:
            line = str(line).strip()
            if not ROUTE_LINE.match(line) and fallback_target:
                line = f"{' '.join(words(line))} \u2192 {fallback_target}"
            if ROUTE_LINE.match(line):
                km = ROUTE_LINE.match(line)
                assert km is not None
                kw, target = km.group("kw"), km.group("t")
                lines.append(f"{pad(kw, target)} \u2192 {target}")
        if lines:
            neuron["lines"] = lines
            plan["neuron"] = neuron

    idx = str(plan.get("index_line") or "").strip()
    m = ROUTE_LINE.match(idx)
    if m:
        kw, target = m.group("kw"), m.group("t")
        plan["index_line"] = f"{pad(kw, target)} \u2192 {target}"
        return plan

    # no usable line: rebuild one from the plan's own names
    target = ""
    if plan["mode"] == "new":
        target = str((plan.get("neuron") or {}).get("name") or "").strip()
    else:
        target = str(plan.get("target") or "").strip()
    if target and ROUTE_LINE.match("x \u2192 " + target):
        kw = " ".join(words(idx)) or " ".join(words(target[:-3].replace("_", " ").replace("-", " ")))
        if kw:
            plan["index_line"] = f"{pad(kw, target)} \u2192 {target}"
            return plan
    plan.pop("index_line", None)  # legal on update; memwrite sorts it out on new
    return plan


def plan_once(store: pathlib.Path, body: str, context_block: str, heading: str,
              dry_run: bool) -> tuple[list[str], list[tuple], int]:
    """One message -> plans -> memwrite. Returns (written, failed, tokens)."""
    user = f"{heading}\n{context_block or '(none matched)'}\n\nTRANSCRIPT:\n{body}"
    plans, tokens = [], 0
    for attempt in (1, 2):
        text, tok = lookup.call(SYSTEM, user + ("" if attempt == 1 else
                                                "\n\nReturn ONLY the JSON object. No prose, no markdown fences, no trailing text."),
                                max_tokens=12000)
        tokens += tok
        plans = extract_plans(text)
        if plans:
            break
        if attempt == 2:
            print("optimize: unparseable model output, head follows:", file=sys.stderr)
            print((text or "")[:300], file=sys.stderr)
    if not plans:
        # last resort: keep the facts rather than lose them to a malformed reply
        slug = "notes-" + __import__("hashlib").sha1(body.encode()).hexdigest()[:6]
        words = [w for w in re.findall(r"[a-z][a-z0-9_.\-]{2,}", body.lower())
                 if w not in {"the", "and", "for", "with", "from", "that", "this"}]
        kws, seen = [], set()
        for w in words:
            if w not in seen:
                kws.append(w); seen.add(w)
            if len(kws) >= 6:
                break
        plans = [{"mode": "new",
                  "neuron": {"name": slug + ".md",
                             "lines": [" ".join(kws) + " → " + slug + "-notes.md"]},
                  "engrams": [{"name": slug + "-notes.md",
                               "content": f"# Notes — {body[3:60].strip()}\nPart of: {slug}.md.\n\n"
                                          + body[:5000]}],
                  "index_line": " ".join(kws) + " → " + slug + ".md"}]
        print("optimize: fell back to a raw-notes engram", file=sys.stderr)

    written, failed = [], []
    for plan in plans:
        plan = repair_plan(plan, body, index_keywords(store), index_targets(store))
        # an engram that already exists aborts the whole plan in memwrite; keep
        # the route and drop just the colliding file so the facts still land
        if plan.get("mode") == "new":
            fresh = [e for e in (plan.get("engrams") or [])
                     if isinstance(e, dict) and not (store / str(e.get("name", ""))).exists()]
            if len(fresh) != len(plan.get("engrams") or []):
                plan["engrams"] = fresh
                if not fresh:
                    continue
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            path = f.name
        cmd = [sys.executable, str(MEMWRITE), "--store", str(store), "--plan", path,
               "--quiet"] + (["--dry-run"] if dry_run else ["--allow-rewrite"])
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            written.append(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ok")
        else:
            failed.append((plan.get("mode"), (r.stdout + r.stderr).strip().splitlines()[-1:]))
        os.unlink(path)
    return written, failed, tokens


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--session")
    ap.add_argument("--transcript")
    ap.add_argument("--state-db",
                    help="session database to read (default: the store's sibling state.db)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--max-messages", type=int, default=60)
    ap.add_argument("--full-index", action="store_true",
                    help="send the whole index instead of the candidate block")
    ap.add_argument("--include-assistant", action="store_true",
                    help="also optimise assistant turns (default: user only)")
    args = ap.parse_args()
    store = pathlib.Path(args.store).expanduser()

    wm = load_watermark()
    if args.transcript:
        msgs = transcript_messages(args.transcript)
        key = f"{store.resolve()}::transcript:" + pathlib.Path(args.transcript).name
    elif args.session:
        key = f"{store.resolve()}::{args.session}"
        db = pathlib.Path(args.state_db).expanduser() if args.state_db else resolve_state_db(store)
        after = 0 if args.force else int(wm.get(key, 0))
        msgs = session_messages(db, args.session, after, args.max_messages)
    else:
        print("optimize: need --session or --transcript", file=sys.stderr)
        return 2

    if not args.include_assistant:
        msgs = [m for m in msgs if m.get("role") == "user"]
    msgs = [m for m in msgs if (m.get("content") or "").strip()]
    if not msgs:
        print("optimize: nothing new to remember")
        return 0

    heading = ("CANDIDATES (existing memories; create new if none covers the facts):"
               if not args.full_index else "INDEX (existing memories):")
    written_total, failed_total, tokens_total, processed = [], [], 0, int(wm.get(key, 0))
    for msg in msgs:
        body = f"[{msg['role']}] {msg['content']}"
        if len(body.strip()) < 80:
            processed = msg["id"]
            continue
        if len(body) > 12000:
            body = body[-12000:]
        block = compact_index(store) if args.full_index else candidate_block(store, body)
        written, failed, tokens = plan_once(store, body, block, heading, args.dry_run)
        tokens_total += tokens
        written_total += written
        if failed:
            failed_total += failed
            break
        processed = msg["id"]

    if not args.dry_run and not failed_total and args.session:
        wm[key] = processed
        wm["last_run"] = time.time()
        save_watermark(wm)
    elif not args.dry_run and args.session:
        print(f"optimize: {len(failed_total)} failure(s); watermark stays at "
              f"{wm.get(key, 0)} so the failed message is retried", file=sys.stderr)

    if not args.quiet:
        print(f"messages: {len(msgs)}  written: {len(written_total)}  failed: {len(failed_total)}"
              f"  ({tokens_total} tokens)")
        for f in failed_total[:3]:
            print("  FAIL", f)
    tag = "dry" if args.dry_run else "written"
    print(f"🧠 Memory Optimized: {len(written_total)} file(s) {tag}, {len(failed_total)} failed")
    return 0 if not failed_total else 1


if __name__ == "__main__":
    raise SystemExit(main())
