#!/usr/bin/env python3
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
# See the NOTICE file for attribution requirements.
"""Check whether memory retrieval routed from the index or brute-forced it.

The failure this exists to catch: the agent answers correctly, but found the
topic file by searching the filesystem instead of routing from the index line.
The answer looks right, so nothing appears broken — but the mechanism does not
scale past a handful of topic files, and it defeats the point of the index.

Usage
-----
  # Inspect the most recent session
  python3 test_retrieval.py --last --expect coffee-log.md

  # Inspect a specific session
  python3 test_retrieval.py --session 20260919_103207_0c045e --expect coffee-log.md

  # Also verify the index line reached the system prompt
  python3 test_retrieval.py --last --expect coffee-log.md --check-prompt

Exit code 0 when the expected file was read and no filesystem search was used
to find it; 1 otherwise. Prints a diagnosis, not just a verdict.
"""
import argparse
import json
import os
import sqlite3
import sys

DEFAULT_DB = os.path.expanduser("~/.hermes/state.db")
SEARCH_TOOLS = {"search_files", "glob", "find", "ls"}


def _connect(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        sys.exit(f"state db not found: {db_path}\n"
                 f"Pass --db if your HERMES_HOME is elsewhere.")
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


def _latest_session(c: sqlite3.Connection) -> str:
    row = c.execute(
        "SELECT session_id FROM messages GROUP BY session_id "
        "ORDER BY MAX(id) DESC LIMIT 1"
    ).fetchone()
    if not row:
        sys.exit("no sessions found in state db")
    return row["session_id"]


def _tool_sequence(c: sqlite3.Connection, sid: str) -> list:
    """Return [(message_id, tool_name, args_dict_or_None, result_text)].

    The result text is captured because it changes the diagnosis: a search that
    found NOTHING did not locate the file, so a subsequent successful read still
    counts as routing. Only a search that returned hits can have done the work.
    """
    seq = []
    rows = c.execute(
        "SELECT id, role, tool_name, tool_calls, content FROM messages "
        "WHERE session_id = ? ORDER BY id",
        (sid,),
    ).fetchall()
    for r in rows:
        d = dict(r)
        if d["role"] == "assistant" and d.get("tool_calls"):
            try:
                for t in json.loads(d["tool_calls"]):
                    fn = t.get("function", {})
                    name = fn.get("name")
                    args = fn.get("arguments")
                    try:
                        args = json.loads(args) if isinstance(args, str) else args
                    except Exception:
                        args = {"_raw": str(args)}
                    seq.append([d["id"], name, args, None])
            except Exception:
                pass
        elif d["role"] == "tool":
            name = d.get("tool_name")
            content = d.get("content") or ""
            for entry in reversed(seq):
                if entry[1] == name and entry[3] is None:
                    entry[3] = content
                    break
    return seq


def _search_found_something(result_text: str) -> bool:
    """True if a search tool call actually returned a hit.

    search_files returns {"total_count": N, "files": [...]} — N == 0 means the
    search found nothing, so it cannot have been how the agent located the file.
    """
    if not result_text:
        return False
    try:
        data = json.loads(result_text)
    except Exception:
        # Non-JSON result (e.g. terminal ls output): treat non-trivial output as a hit.
        head = result_text.strip()
        return len(head) > 2 and "not found" not in head.lower()
    if isinstance(data, dict):
        if "total_count" in data:
            return bool(data.get("total_count"))
        if "files" in data:
            return bool(data.get("files"))
        if "matches" in data:
            return bool(data.get("matches"))
        return False
    if isinstance(data, list):
        return bool(data)
    return False


def _prompt_for_session(c: sqlite3.Connection, sid: str) -> str:
    row = c.execute(
        "SELECT sp.prompt AS prompt FROM sessions s "
        "JOIN system_prompts sp ON s.system_prompt_hash = sp.hash "
        "WHERE s.id = ?",
        (sid,),
    ).fetchone()
    if row and row["prompt"]:
        return row["prompt"]
    row = c.execute(
        "SELECT system_prompt FROM sessions WHERE id = ?", (sid,)
    ).fetchone()
    return (row["system_prompt"] if row and row["system_prompt"] else "") or ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--session", help="session id to inspect")
    ap.add_argument("--last", action="store_true",
                    help="inspect the most recent session")
    ap.add_argument("--expect", required=True,
                    help="topic file the index should have routed to (basename)")
    ap.add_argument("--check-prompt", action="store_true",
                    help="also verify the index reached the system prompt")
    args = ap.parse_args()

    if not args.session and not args.last:
        sys.exit("pass --session <id> or --last")

    c = _connect(args.db)
    sid = args.session or _latest_session(c)
    seq = _tool_sequence(c, sid)

    if not seq:
        print(f"session {sid}: no tool calls recorded")
        return 1

    reads, searches = [], []
    for mid, name, a, res in seq:
        blob = json.dumps(a or {})
        if name == "read_file" and args.expect in blob:
            reads.append((mid, a))
        if name in SEARCH_TOOLS and args.expect.split(".")[0] in blob:
            # A search firing CONCURRENTLY with the read (same message id) is
            # enumeration, not a lookup — the agent already knows the path from
            # the index line. Only a search in an EARLIER message can have been
            # how the file was located.
            if reads and mid == reads[0][0]:
                continue
            searches.append((mid, name, a, _search_found_something(res)))

    print(f"session: {sid}")
    print(f"expected topic file: {args.expect}")
    print(f"tool calls in session: {len(seq)}")
    print()

    ok = True

    if reads:
        print(f"PASS  read_file on {args.expect} (msg {reads[0][0]}).")
    else:
        ok = False
        print(f"FAIL  no read_file on {args.expect}.")

    # The distinction that matters is ORDER plus RESULT: a search that returned
    # hits BEFORE the read means the agent located the file by brute force. A
    # search that returned nothing cannot have been how the file was found — the
    # filename came from the injected index line, which is routing working.
    hit_searches = [(m, n, a) for m, n, a, found in searches if found]
    miss_searches = [(m, n, a) for m, n, a, found in searches if not found]

    search_before_read = False
    if hit_searches:
        first_hit = min(m for m, _n, _a in hit_searches)
        search_before_read = first_hit < reads[0][0] if reads else True

    if search_before_read:
        ok = False
        print()
        print(f"FAIL  a search that RETURNED HITS ran before the read — the file")
        print(f"      was located by brute force, not by the index line:")
        for mid, name, a in sorted(hit_searches)[:5]:
            marker = " <-- before the read" if reads and mid < reads[0][0] else ""
            print(f"        msg {mid}: {name} {json.dumps(a)[:100]}{marker}")
        print()
        print("        The answer may still be correct, but this does not scale")
        print("        past a handful of topic files. The routing instruction is")
        print("        not reaching the model.")
        print("        See references/diagnosing-recall-failure.md, Layer 3.")
    else:
        print("PASS  the file was located by routing, not by search.")

    if miss_searches:
        print()
        print(f"note  {len(miss_searches)} search call(s) returned NOTHING and were")
        print(f"      not how the file was found:")
        for mid, name, a in sorted(miss_searches)[:5]:
            print(f"        msg {mid}: {name} {json.dumps(a)[:100]}")
        print("      A speculative search before a successful read is wasted")
        print("      effort, but it is not a routing failure. If it happens on")
        print("      every retrieval, the routing instruction is too weak or the")
        print("      model is reaching for search by habit.")

    if args.check_prompt:
        print()
        p = _prompt_for_session(c, sid)
        present = "→" in p
        print(f"{'PASS' if present else 'FAIL'}  index present in system prompt "
              f"(prompt {len(p)} chars)")
        if not present:
            ok = False
            print("        MEMORY.md is not reaching the prompt — check that it")
            print("        exists at ~/.hermes/memories/MEMORY.md and that memory")
            print("        is enabled for this profile.")

    print()
    print("RESULT:", "routed from the index" if ok else "retrieval did NOT work as designed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
