#!/usr/bin/env python3
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
# See the NOTICE file for attribution requirements.
"""Test the memory-shaper hook: read-only passthrough vs. write blocking.

Run from the repo root after pointing PLUGIN_DIR at your installed
memory-shaper copy (default: this repo's plugin/memory-shaper).

Cases cover the 2026-09-16 read-lock regression class: the write-lock must
block every write vector (redirect, tee, sed -i, command substitution,
write_file) while still passing pure reads (cat, head, wc) so the agent can
audit the file it maintains.
"""
import importlib
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(REPO, "plugin", "memory-shaper")
sys.path.insert(0, PLUGIN_DIR)
plugin = importlib.import_module("plugin")
importlib.reload(plugin)

M = os.path.expanduser("~/.hermes/memories/MEMORY.md")

cases = [
    ("read-only cat",      "terminal",   {"command": f"cat {M}"},                       False),
    ("read-only head",     "terminal",   {"command": f"head -8 {M}"},                   False),
    ("read-only wc",       "terminal",   {"command": f"wc -c {M}"},                     False),
    ("write redirect",     "terminal",   {"command": f"echo x >> {M}"},                 True),
    ("pipe tee",           "terminal",   {"command": f"cat a | tee {M}"},               True),
    ("sed -i",             "terminal",   {"command": f"sed -i s/a/b/ {M}"},             True),
    ("cmd subst",          "terminal",   {"command": f"cat $({M} )"},                   True),
    ("sort -o redirect",   "terminal",   {"command": f"sort -o {M} x"},                 True),
    ("awk print-redirect", "terminal",   {"command": """awk '{print > "x"}' x | tee MEMORY.md"""}, True),
    ("grep pattern",       "terminal",   {"command": f"grep 'kw1,kw2' {M}"},            False),
    ("write_file",         "write_file", {"path": M, "content": "x"},                   True),
    ("write_file other",   "write_file", {"path": "/tmp/other.md", "content": "x"},     False),
    # Audit-lockout regression guard: read_file carries the SAME `path` field as
    # write_file, so a path-only check wrongly refused reads of the index the
    # agent is responsible for maintaining. Reads must always pass.
    ("read_file index",    "read_file",  {"path": M},                                  False),
    ("read_file other",    "read_file",  {"path": "/tmp/other.md"},                     False),
    ("patch index",        "patch",      {"path": M, "old_string": "a", "new_string": "b"}, True),
]

fails = 0
for name, tool, args, expect_block in cases:
    d = plugin.handle_pre_tool_call(tool, args)
    blocked = isinstance(d, dict) and d.get("action") == "block"
    ok = blocked == expect_block
    fails += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:18} blocked={blocked} expected={expect_block}")

# --- separator-line classification -------------------------------------------
# Hermes' memory store joins entries with "\n§\n" (tools/memory_tool_store.py).
# The dynamic-memory format is newline-delimited, so those lines are runtime
# artifacts and must never be treated as entries.
sep_cases = [
    ("bare section sign", "§", True),
    ("ruler",             "═" * 46, True),
    ("equals ruler",      "======", True),
    ("whitespace padded", "  §  ", True),
    ("index line",        "java,jvm,heap,gc,profiling → java-performance.md", False),
    ("line containing §", "sigma,section,§,mark,glyph → symbols.md", False),
    ("empty",             "", False),
]
print()
for name, text, expect_sep in sep_cases:
    got = plugin._is_separator_line(text)
    ok = got == expect_sep
    fails += (not ok)
    shown = text if len(text) <= 24 else text[:24] + "…"
    print(f"  [{'PASS' if ok else 'FAIL'}] sep:{name:18} is_sep={got} expected={expect_sep}  ({shown!r})")

# A replace that targets a separator line must be refused — deleting the
# runtime's own boundary is not an index edit. This needs a file that actually
# contains a separator, so point the plugin at a temp dir rather than relying on
# whatever happens to be in the real memories directory.
print()
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as td:
    fake = Path(td) / "MEMORY.md"
    fake.write_text(
        "java,jvm,heap,gc,profiling,jmx,tuning \u2192 java-performance.md\n"
        "\u00a7\n"
        "router,firmware,subnet,dns,dhcp,modem,openwrt \u2192 home-network.md\n",
        encoding="utf-8",
    )
    plugin.MEMORY_MD = fake
    sep_target = plugin.handle_pre_tool_call(
        "memory",
        {"action": "replace", "target": "memory", "old_text": "\u00a7",
         "content": "a,b,c,d,e \u2192 x.md"},
    )
    blocked = isinstance(sep_target, dict) and sep_target.get("action") == "block"
    msg = (sep_target or {}).get("message", "") if isinstance(sep_target, dict) else ""
    ok = blocked and "separator" in msg
    fails += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] replace on separator refused  blocked={blocked} "
          f"reason={'separator' if 'separator' in msg else msg[:48]}")

    # A replace targeting a real entry line must still work.
    real = plugin.handle_pre_tool_call(
        "memory",
        {"action": "replace", "target": "memory",
         "old_text": "java,jvm", "content": "jvm,heap,gc,profiling,jmx,tuning,xmx \u2192 java-performance.md"},
    )
    real_blocked = isinstance(real, dict) and real.get("action") == "block"
    ok = not real_blocked
    fails += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] replace on real entry allowed  blocked={real_blocked}")

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
