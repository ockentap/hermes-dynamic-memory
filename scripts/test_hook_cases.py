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
]

fails = 0
for name, tool, args, expect_block in cases:
    d = plugin.handle_pre_tool_call(tool, args)
    blocked = isinstance(d, dict) and d.get("action") == "block"
    ok = blocked == expect_block
    fails += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:18} blocked={blocked} expected={expect_block}")

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
