#!/usr/bin/env python3
"""optimize — the idle memory optimiser behind the "🧠 Memory Optimized" hook.

Reads the new part of a session (or a transcript file), asks the model for
memwrite plans that capture every durable fact, applies them through memwrite,
and reports one line.

    python3 scripts/optimize.py --store ~/.hermes/memories --session <id>
    python3 scripts/optimize.py --store ~/.hermes/memories --transcript t.json
    python3 scripts/optimize.py ... --dry-run | --force | --quiet

A watermark per session (`~/.hermes/state/optimizer-watermark.json`) means each
message is summarised once. `--force` ignores it.
"""
from __future__ import annotations

import argparse
import json
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

SYSTEM = """You maintain a dynmem memory store: MEMORY.md is an index of neurons,
a neuron is a table of route lines 'keyword keyword → child.md', and engrams are
the terminal memory files.

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
- If a fact belongs to an existing memory shown in the index, use mode "update"
  with that file as target instead of creating a duplicate.

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


def session_messages(session_id: str, after_id: int, limit: int = 60) -> tuple[list[dict], int]:
    c = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    rows = c.execute(
        "select id, role, content from messages where session_id=? and id>? and role in ('user','assistant')"
        " and content is not null order by id limit ?", (session_id, after_id, limit)).fetchall()
    msgs = [{"id": r[0], "role": r[1], "content": r[2]} for r in rows]
    return msgs, (msgs[-1]["id"] if msgs else after_id)


def transcript_messages(path: str) -> list[dict]:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("messages", [])
    return [{"id": i, "role": m.get("role", "user"), "content": m.get("content", "")}
            for i, m in enumerate(data, 1)]


def compact_index(store: pathlib.Path, limit: int = 8) -> str:
    lines = []
    for line in (store / "MEMORY.md").read_text(encoding="utf-8").splitlines():
        if "→" not in line or line.lstrip().startswith("#"):
            continue
        kw, target = line.rsplit("→", 1)
        kws = " ".join(kw.split()[:limit])
        lines.append(f"{kws} → {target.strip()}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--session")
    ap.add_argument("--transcript")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--max-messages", type=int, default=60)
    args = ap.parse_args()
    store = pathlib.Path(args.store).expanduser()

    wm = load_watermark()
    if args.transcript:
        msgs = transcript_messages(args.transcript)
        last_id = msgs[-1]["id"] if msgs else 0
        key = "transcript:" + pathlib.Path(args.transcript).name
    elif args.session:
        key = args.session
        msgs, last_id = session_messages(args.session, 0 if args.force else int(wm.get(key, 0)),
                                         args.max_messages)
    else:
        print("optimize: need --session or --transcript", file=sys.stderr)
        return 2

    body = "\n\n".join(f"[{m['role']}] {m['content']}" for m in msgs if m.get("content"))
    if len(body.strip()) < 200:
        print("optimize: nothing new to remember")
        return 0
    if len(body) > 24000:
        body = body[-24000:]

    user = f"INDEX (existing memories):\n{compact_index(store)}\n\nTRANSCRIPT:\n{body}"
    plans, tokens = [], 0
    for attempt in (1, 2):
        text, tok = lookup.call(SYSTEM, user + ("" if attempt == 1 else
                                                "\n\nReturn JSON only, no prose."), max_tokens=6000)
        tokens += tok
        try:
            start, end = text.find("{"), text.rfind("}")
            plans = json.loads(text[start:end + 1]).get("plans", [])
            if plans:
                break
        except Exception:
            plans = []
    if not plans:
        print("optimize: model returned no usable plan after 2 attempts", file=sys.stderr)
        return 3

    written, failed = [], []
    for plan in plans:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            path = f.name
        cmd = [sys.executable, str(MEMWRITE), "--store", str(store), "--plan", path,
               "--quiet"] + (["--dry-run"] if args.dry_run else ["--allow-rewrite"])
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            written.append(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ok")
        else:
            failed.append((plan.get("mode"), r.stdout.strip().splitlines()[-1:] or r.stderr[-160:]))
        os.unlink(path)

    if not args.dry_run:
        if failed:
            # do not advance: the next trigger retries the same messages
            print(f"optimize: {len(failed)} plan(s) failed; watermark kept at "
                  f"{wm.get(key, 0)} for a retry", file=sys.stderr)
        else:
            wm[key] = last_id
            save_watermark(wm)
    if not args.quiet:
        print(f"plans: {len(plans)}  written: {len(written)}  failed: {len(failed)}  ({tokens} tokens)")
        for f in failed[:3]:
            print("  FAIL", f)
    tag = "dry" if args.dry_run else "written"
    print(f"🧠 Memory Optimized: {len(written)} file(s) {tag}, {len(failed)} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
