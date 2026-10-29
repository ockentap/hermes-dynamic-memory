#!/usr/bin/env python3
"""Prove the guard follows the ACTIVE profile, not the launch env."""
import os, sys, tempfile
from pathlib import Path

# Launch env points at profile A
homeA = tempfile.mkdtemp(prefix="profA-")
mdA = Path(homeA) / "memories"; mdA.mkdir()
(mdA / "MEMORY.md").write_text("alpha,beta → ab.md\n")
os.environ["HERMES_HOME"] = homeA

sys.path.insert(0, "/opt/hermes")
sys.path.insert(0, "/opt/hermes/plugins/memory-shaper")
from hermes_constants import set_hermes_home_override, get_hermes_home
import plugin

# Context switches to profile B (what a multiplexed gateway does per turn)
homeB = tempfile.mkdtemp(prefix="profB-")
mdB = Path(homeB) / "memories"; mdB.mkdir()
(mdB / "MEMORY.md").write_text("gamma,delta → gd.md\n")
set_hermes_home_override(homeB)

fails = 0
# 1. resolver follows the override, not env
r = plugin._hermes_home()
ok = str(r) == str(Path(homeB).resolve()) or str(r) == homeB
print(f"[{'PASS' if ok else 'FAIL'}] _hermes_home follows context override (got {r}, want {homeB}, env is {homeA})")
fails += 0 if ok else 1

# 2. patch guard reads profile B's file: old_text matching ONLY B's content
res = plugin.handle_pre_tool_call("memory", {
    "action": "patch", "target": "memory",
    "old_text": "gamma", "content": "gamma-x"})
# span in B's line -> resulting "gamma-x,delta → gd.md" is valid -> should PASS
ok = res == {}
print(f"[{'PASS' if ok else 'FAIL'}] patch evaluated against profile B file (result={str(res)[:60]})")
fails += 0 if ok else 1

# 3. a patch matching ONLY A's content must be a no-match (pass-through to tool,
#    which in B's home finds nothing) — crucially it must NOT read A's file and
#    validate against it as an entry
res2 = plugin.handle_pre_tool_call("memory", {
    "action": "patch", "target": "memory",
    "old_text": "alpha,beta → ", "content": "WRONG-PROFILE "})
# If the guard leaked profile A, it would compute a resulting line from A's file
# and BLOCK with a malformed-line message. Correct behaviour: B has no such
# entry -> guard defers (pass), the tool itself refuses the no-match.
ok = res2 == {}
msg = res2.get("message", "")[:80] if isinstance(res2, dict) else ""
print(f"[{'PASS' if ok else 'FAIL'}] no cross-profile read of A's entries (msg={msg})")
fails += 0 if ok else 1

# 4. verbose routing hint names profile B's dir
res3 = plugin.handle_pre_tool_call("memory", {
    "action": "add", "target": "memory",
    "content": "a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z " * 4})
hintB = homeB in res3.get("message", "") and homeA not in res3.get("message", "")
print(f"[{'PASS' if hintB else 'FAIL'}] routing hint points at profile B memories dir")
fails += 0 if hintB else 1

print("PROFILE-SCOPE: " + ("GREEN" if fails == 0 else f"RED ({fails})"))
sys.exit(1 if fails else 0)
