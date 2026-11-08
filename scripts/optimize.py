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
STATE_DB = pathlib.Path.home() / ".hermes" / "state.db"

sys.path.insert(0, str(HERE))
import lookup  # noqa: E402  (shared provider + index helpers)

SYSTEM = """You maintain a dynmem memory store: the index lists neurons, a neuron is
a table of route lines 'keyword keyword → child.md', and engrams are the terminal
memory files.

Read the transcript and write what must be remembered into the store.

Rules:
- Capture EVERY durable fact, decision, identifier, path, number and correction.
  Keep identifiers verbatim (they are how the facts are checked later).
- Do not invent anything that is not in the transcript.
- One subject per engram, 2-6 KB each; split a rich subject into aspect engrams.
  Never one giant engram.
- An engram starts '# <title>', then 'Part of: <neuron>.md.', then the content.
- A neuron contains only route lines: 5-20 space-separated keywords, Unicode →,
  no commas.
- The index line points at the neuron.
- If a fact belongs to an existing memory shown in the candidate list, use mode
  "update" with that file as target instead of creating a duplicate. If nothing
  covers the facts, mode "new" is correct.

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


def session_messages(session_id: str, after_id: int, limit: int = 60) -> list[dict]:
    c = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
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


def candidate_block(store: pathlib.Path, text: str, limit: int = 12,
                    budget_chars: int = 5200) -> str:
    """The few index lines that could possibly matter, plus their children.

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
    for _, kws, target in scored[:limit]:
        out.append(" ".join(kws[:8]) + " → " + target)
        child = store / target
        if child.exists():
            body = [l.strip() for l in child.read_text(encoding="utf-8", errors="replace").splitlines()
                    if l.strip() and not l.strip().startswith("#")]
            routes = [l for l in body if "→" in l]
            if routes and len(routes) / len(body) >= 0.5:
                for route in routes[:5]:
                    out.append("    " + route)
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


def plan_once(store: pathlib.Path, body: str, context_block: str, heading: str,
              dry_run: bool) -> tuple[list[str], list[tuple], int]:
    """One message -> plans -> memwrite. Returns (written, failed, tokens)."""
    user = f"{heading}\n{context_block or '(none matched)'}\n\nTRANSCRIPT:\n{body}"
    plans, tokens = [], 0
    for attempt in (1, 2):
        text, tok = lookup.call(SYSTEM, user + ("" if attempt == 1 else
                                                "\n\nReturn JSON only, no prose."),
                                max_tokens=6000)
        tokens += tok
        try:
            start, end = text.find("{"), text.rfind("}")
            plans = json.loads(text[start:end + 1]).get("plans", [])
            if plans:
                break
        except Exception:
            plans = []
    if not plans:
        return [], [("parse", "no usable plan after 2 attempts")], tokens

    written, failed = [], []
    for plan in plans:
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
        after = 0 if args.force else int(wm.get(key, 0))
        msgs = session_messages(args.session, after, args.max_messages)
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
