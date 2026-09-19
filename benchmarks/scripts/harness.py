#!/usr/bin/env python3
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
# See the NOTICE file for attribution requirements.
"""Shared harness for the memory benchmarks.

Every benchmark needs the same three things and the same two guarantees:

  - install a memory fixture into a container, in native or dynamic encoding
  - ask N questions, one fresh session each, capturing raw answers
  - GRADE the answers

The grading is the part that went wrong repeatedly while producing these
results, so it is worth being explicit about why it looks like this:

  1. A plain substring match is WRONG. It counts a correct refusal as a pass
     whenever the answer mentions the probe's keywords while explaining that it
     does not know the fact. "I don't have that recorded — nothing there states
     a merge preference" scored as a pass for a question about rebase-merging.

  2. A blanket refusal-regex is ALSO wrong, in the other direction. It fails true
     answers whose denial was about additional detail rather than the fact:
     "Conversational — you picked it up living in Berlin. I have no formal level
     recorded" is a correct answer that a naive regex marks as a refusal.

  Three automated graders produced 42/50, 28/50 and 26/50 for the same run. At
  that point tuning the grader until it agrees with you is not measurement.

So this module does NOT pretend to grade automatically. It scores mechanically
and then surfaces every disagreement for human adjudication, which is how the
published numbers were actually produced. `adjudicate()` below is the workflow.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from typing import Iterable

# Denial language observed in real answers. Used to FLAG for review, not to decide.
DENIAL_MARKERS = [
    r"i don'?t have", r"i do not have", r"nothing (?:on file|in my|there|recorded)",
    r"not (?:recorded|in my (?:memory|notes)|on file)", r"nothing .{0,25}records",
    r"i don'?t know", r"no .{0,25}(?:record|mention|entry|note)s?\b",
    r"isn'?t (?:anything|recorded)", r"i have no", r"came back empty",
    r"0 sessions indexed", r"not something i (?:actually )?know", r"no entry about",
    r"i won'?t invent", r"nothing in my memory", r"don'?t have this one",
    r"i checked .{0,50}(?:nothing|no )", r"nothing .{0,30}answers that",
    r"never comes up", r"nothing (?:in|about) (?:this|the) session",
    r"no .{0,20}material", r"nothing about your", r"not on file",
    r"unable to find", r"can'?t find", r"cannot find",
]
_DENIAL = re.compile("|".join(DENIAL_MARKERS), re.I)


# Docker sometimes needs `sudo` (or `docker` may be usable directly if the user
# is in the docker group). Set MEMBENCH_DOCKER to override, e.g.:
#   export MEMBENCH_DOCKER="sudo docker"
DOCKER = os.environ.get("MEMBENCH_DOCKER", "docker")


def sh(cmd: str, timeout: int = 600, check: bool = True) -> str:
    """Run a shell command, raising on failure unless check=False."""
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise SystemExit(f"FAILED: {cmd[:100]}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def dk(sub: str, timeout: int = 600, check: bool = True) -> str:
    """Run a docker subcommand honouring the MEMBENCH_DOCKER prefix."""
    return sh(f"{DOCKER} {sub}", timeout=timeout, check=check)


def load_results(path: str) -> list[dict]:
    """Load a results file, tolerating both the stamped object shape
    ({"_benchmark_conditions": {...}, "results": [...]}) and a bare list."""
    import json as _json
    data = _json.load(open(path))
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    if isinstance(data, dict):
        return [data]
    return data


def benchmark_conditions(path: str) -> dict:
    """Return the recorded run conditions (model, provider, versions) if present."""
    import json as _json
    data = _json.load(open(path))
    if isinstance(data, dict):
        return data.get("_benchmark_conditions", {})
    return {}


def strip_meta(text: str) -> str:
    """Drop Hermes CLI session banners so only the answer body remains."""
    return "\n".join(
        l for l in text.splitlines()
        if not l.startswith("session_id") and not l.startswith("⚠️")
    )


def ask(container: str, prompt: str, timeout: int = 400) -> str:
    """Ask a container a single question in a fresh session."""
    cmd = f"{DOCKER} exec {container} hermes chat -q {shlex.quote(prompt)} -Q"
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")


def clean_container(name: str) -> None:
    """Rebuild a container and wipe ALL session state, so memory is the only
    possible source of an answer.

    This is not optional. An earlier version of these benchmarks ran on
    containers holding ~1,000 messages of setup conversation, and questions were
    answered out of state.db instead of memory. Verify with `assert_clean`
    before trusting any result.
    """
    memdir = "/root/.hermes/memories"
    sh(f"{DOCKER} exec {name} bash -c '"
       f"rm -rf /root/.hermes/sessions /root/.hermes/sandboxes; "
       f"rm -f /root/.hermes/state.db /root/.hermes/state.db-shm "
       f"/root/.hermes/state.db-wal /root/.hermes/state.db.*.lock; "
       f"mkdir -p {memdir} /root/.hermes/sessions; "
       f"find {memdir} -maxdepth 1 -type f -delete'")


def assert_clean(name: str) -> None:
    """Fail loudly unless the container has zero history and zero memories."""
    out = sh(f"{DOCKER} exec {name} bash -c '"
             f"echo files=$(find /root/.hermes/memories -type f 2>/dev/null | wc -l); "
             f"echo sessions=$(find /root/.hermes/sessions -type f 2>/dev/null | wc -l); "
             f"test -f /root/.hermes/state.db && echo state=present || echo state=absent'")
    files = re.search(r"files=(\d+)", out)
    sessions = re.search(r"sessions=(\d+)", out)
    if not files or not sessions or files.group(1) != "0" or sessions.group(1) != "0":
        raise SystemExit(f"{name} is NOT clean:\n{out}")
    print(f"  {name}: 0 memories, 0 sessions, state.db absent")


def install_dynamic(container: str, categories: dict[str, list[dict]],
                    keywords: dict[str, str]) -> None:
    """Write topic files + a flat keyword index. Detail lives on disk.

    `categories` maps a topic name to a list of {"id","text"} memories.
    `keywords` maps a topic name to its comma-separated index keywords.
    """
    memdir = "/root/.hermes/memories"
    idx_name = "MEM" + "ORY" + ".md"
    local = "/tmp/_bm_install"
    os.makedirs(local, exist_ok=True)
    for cat, mems in categories.items():
        body = f"# {cat.title()} — recorded facts\n\n"
        body += "".join(f"- **{m['id']}**: {m['text']}\n" for m in mems)
        with open(f"{local}/{cat}.md", "w") as f:
            f.write(body)
        sh(f"{DOCKER} cp {local}/{cat}.md {container}:/tmp/{cat}.md")
    idx = "\n".join(f"{keywords[c]} → {c}.md" for c in categories) + "\n"
    with open(f"{local}/index.txt", "w") as f:
        f.write(idx)
    sh(f"{DOCKER} cp {local}/index.txt {container}:/tmp/idx.txt")
    cats = " ".join(categories)
    sh(f"{DOCKER} exec {container} bash -c '"
       f"for c in {cats}; do cp /tmp/$c.md {memdir}/$c.md; done; "
       f"cp /tmp/idx.txt {memdir}/{idx_name}'")


def install_native(container: str, memories: Iterable[dict], cap: int = 2200) -> dict:
    """Write memories as flat entries until the character cap refuses the rest.

    Returns {"accepted": [ids], "refused": [ids], "chars": int}. The refusal set
    is a RESULT, not a setup detail — it is the measurement of what the cap costs.
    """
    memdir = "/root/.hermes/memories"
    idx_name = "MEM" + "ORY" + ".md"
    sep = "\n\u00a7\n"
    accepted, refused, used = [], [], 0
    for m in memories:
        line = f"{m['id']}: {m['text']}"
        cost = len(line) + (len(sep) if accepted else 0)
        if used + cost <= cap:
            accepted.append(line)
            used += cost
        else:
            refused.append(m["id"])
    local = "/tmp/_bm_install"
    os.makedirs(local, exist_ok=True)
    with open(f"{local}/native.txt", "w") as f:
        f.write(sep.join(accepted))
    sh(f"{DOCKER} cp {local}/native.txt {container}:/tmp/n.txt")
    sh(f"{DOCKER} exec {container} bash -c 'cp /tmp/n.txt {memdir}/{idx_name}'")
    return {"accepted": [l.split(":", 1)[0] for l in accepted],
            "refused": refused, "chars": used}


def score(text: str, needles: list[str]) -> tuple[bool, str]:
    """Mechanical score plus the REASON, so disagreements can be reviewed.

    Returns (passed, why). Treat `why` starting with 'denial(' or 'no-needle' as
    'needs human review', not as a settled failure — see the module docstring.
    """
    t = text.lower()
    if not any(n.lower() in t for n in needles):
        return False, "no-needle"
    m = _DENIAL.search(text)
    if m:
        return False, f"denial({m.group(0)[:30]!r})"
    return True, "ok"


def adjudicate(rows: list[dict], overrides: dict[tuple[str, str], tuple[bool, str]]) -> dict:
    """Apply human decisions over the mechanical score and return the final tally.

    `overrides` maps (id, who) -> (passed, reason), where `who` is 'native' or
    'dynamic'. Every override must have a written reason: the published results
    depend on these calls, so they need to be defensible line by line.

    Tolerates the key names used by the committed result files, which predate this
    harness: a mechanical score may live under '<who>_ok' (this harness) or
    '<who>_correct' (the archived runs).
    """
    def mech(r: dict, who: str) -> bool:
        for k in (f"{who}_ok", f"{who}_correct", f"{who}_clean"):
            if k in r:
                return bool(r[k])
        return False

    for r in rows:
        r.setdefault("id", r.get("fact"))
        for who in ("native", "dynamic"):
            key = (r["id"], who)
            if key in overrides:
                passed, reason = overrides[key]
                r[f"{who}_final"] = passed
                r[f"{who}_final_reason"] = f"manual: {reason}"
            else:
                r[f"{who}_final"] = mech(r, who)
                r[f"{who}_final_reason"] = r.get(f"{who}_why", "mechanical")
    return {
        "native": sum(1 for r in rows if r["native_final"]),
        "dynamic": sum(1 for r in rows if r["dynamic_final"]),
        "total": len(rows),
    }
