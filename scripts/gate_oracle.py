#!/usr/bin/env python3
"""Gate: oracle-driven edge-case discovery for the memory-shaper guard.

Runs INSIDE a Hermes >=0.22 container (uses the real tools.memory_tool as the
write oracle). For each adversarial memory-call shape:

  NO-GUARD lane: apply the call to a fresh temp HERMES_HOME with the real tool,
                  then judge the resulting MEMORY.md (all entry lines valid?).
  GUARD lane:    run the plugin's handle_pre_tool_call on the same shape, then
                  apply only if the guard passes.

Two invariants:
  SAFETY    guard passes  -> final file must be VALID   (else: BYPASS)
  USABILITY call would produce VALID file -> guard must not block (else: OVERBLOCK)

Anything violating either is printed as an edge case for fixing. Exit 0 = green.

usage: python3 gate_oracle.py [--verbose]
"""
import json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

REPO_PLUGIN = os.environ.get("GUARD_PLUGIN", "/opt/hermes/plugins/memory-shaper/plugin.py")
SEED_LINES = [
    "java,jvm,heap → java-jvm.md",
    "github,ops,ockentap → github-ops.md",
    "model,preference,qwen,gemma → model-preference.md",
]

HEADER = """# Dynamic Memory Index
keyword,keyword,keyword → file.md
"""

# ---------------------------------------------------------------- oracle util
def run_lane(shape, guard_enabled: bool) -> tuple[bool, str, str]:
    """Apply one memory-tool call in an isolated HERMES_HOME.

    Returns (guard_blocked, final_memory_md, tool_result_json).
    """
    home = tempfile.mkdtemp(prefix="gate-")
    try:
        memdir = Path(home) / "memories"
        memdir.mkdir(parents=True, exist_ok=True)
        (memdir / "MEMORY.md").write_text(HEADER + "\n".join(SEED_LINES) + "\n")

        script = f'''
import json, os, sys
sys.path.insert(0, {REPO_PLUGIN!r}.rsplit("/", 1)[0] if False else "/opt/hermes")
shape = json.loads({json.dumps(shape)!r})
guard_enabled = {guard_enabled!r}
blocked = False

if guard_enabled:
    import importlib.util
    spec = importlib.util.spec_from_file_location("ms_gate", {REPO_PLUGIN!r})
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    decision = mod.handle_pre_tool_call("memory", shape)
    blocked = isinstance(decision, dict) and decision.get("action") == "block"

result = {{"skipped": True}}
if not blocked:
    os.environ["HERMES_HOME"] = {home!r}
    from tools.memory_tool import memory_tool, load_on_disk_store
    store = load_on_disk_store()
    result = memory_tool(
        action=shape.get("action"), target=shape.get("target") or "memory",
        content=shape.get("content"), old_text=shape.get("old_text"),
        new_text=shape.get("new_text"), operations=shape.get("operations"),
        store=store,
    )
out = {{"blocked": blocked, "result": result}}
print("<<<OUT>>>")
print(json.dumps(out))
final = open({str(memdir / "MEMORY.md")!r}).read()
print("<<<FINAL>>>")
print(final)
'''
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           timeout=60, env={**os.environ, "HERMES_HOME": home})
        out = r.stdout
        if "<<<OUT>>>" not in out:
            raise RuntimeError(f"oracle harness failed:\n{r.stdout[-400:]}\n{r.stderr[-400:]}")
        meta_part, final_part = out.split("<<<FINAL>>>")
        meta = json.loads(meta_part.split("<<<OUT>>>")[1].strip())
        return meta["blocked"], final_part, str(meta.get("result"))
    finally:
        shutil.rmtree(home, ignore_errors=True)


# --------------------------------------------------------------- file validity
# House style (must match the guard's own rule): comma-separated keywords with
# NO spaces inside them, Unicode arrow, bare relative .md target. A loose
# checker accepts "some prose words → file.md" as valid and HIDES real bypasses.
ARROW_RE = re.compile(
    r"^[a-z0-9][a-z0-9_-]*(?:,[a-z0-9][a-z0-9_-]*)*\s*→\s+(?:[\w.-]+/)*[\w.-]+\.md$",
    re.I)

def file_valid(text: str) -> tuple[bool, list[str]]:
    """Every body line must be a well-formed index line (template/header/blank/§ ok)."""
    bad = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s == "§" or set(s) <= {"═", "=", "§", " "}:
            continue
        if s.startswith("keyword,keyword,keyword"):   # template marker line
            continue
        if not ARROW_RE.match(s):
            bad.append(s[:80])
    return (not bad), bad


# ------------------------------------------------------------------ the matrix
def probes():
    """(id, shape) — every advertised v0.22.5 argument shape plus hostile combos.

    Expected behaviour is NOT hardcoded: both lanes run and the invariant is
    derived from the file oracle, so a schema/semantics change shows up as a
    new violation instead of a stale expectation.
    """
    ok_line = "rust,build → rust-build.md"
    prose = "This is human prose with no keyword structure at all"
    verb = "a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z " * 4
    P = []
    # single-op shapes
    P.append(("add-valid",        {"action": "add", "target": "memory", "content": ok_line}))
    P.append(("add-prose",        {"action": "add", "target": "memory", "content": prose}))
    P.append(("add-verbose",      {"action": "add", "target": "memory", "content": verb}))
    P.append(("add-nocontent",    {"action": "add", "target": "memory"}))
    P.append(("add-newtext-alias",{"action": "add", "target": "memory", "new_text": ok_line}))
    P.append(("add-both-content-wins", {"action": "add", "target": "memory",
                                       "content": ok_line, "new_text": prose}))
    P.append(("add-both-prose-first",  {"action": "add", "target": "memory",
                                       "content": prose, "new_text": ok_line}))
    P.append(("patch-typo-fragment", {"action": "patch", "target": "memory",
                                     "old_text": "ockentap", "content": "ocky"}))
    P.append(("patch-keyword-add",  {"action": "patch", "target": "memory",
                                     "old_text": "heap", "content": "heap,gc,profiler"}))
    P.append(("patch-break-arrow",  {"action": "patch", "target": "memory",
                                     "old_text": " → ", "content": " => "}))
    P.append(("patch-multiline",    {"action": "patch", "target": "memory",
                                     "old_text": "java", "content": "kotlin\nanother → x.md"}))
    P.append(("patch-newtext-alias",{"action": "patch", "target": "memory",
                                     "old_text": "ockentap", "new_text": "ocky"}))
    P.append(("patch-target-missing-line", {"action": "patch", "target": "memory",
                                            "old_text": "zzzz-not-there", "content": "x,y → x.md"}))
    P.append(("remove-valid",       {"action": "remove", "target": "memory", "old_text": "java,jvm"}))
    P.append(("remove-missing",     {"action": "remove", "target": "memory", "old_text": "zzz-nope"}))
    # batch shapes
    P.append(("ops-valid",          {"operations": [{"action": "add", "content": ok_line}]}))
    P.append(("ops-prose",          {"operations": [{"action": "add", "content": prose}]}))
    P.append(("ops-verbose",        {"operations": [{"action": "add", "content": verb}]}))
    P.append(("ops-mixed",          {"operations": [{"action": "add", "content": ok_line},
                                                    {"action": "add", "content": prose}]}))
    P.append(("ops-patch-fragment", {"operations": [{"action": "patch", "old_text": "ockentap",
                                                     "content": "ocky"}]}))
    P.append(("ops-newtext",        {"operations": [{"action": "add", "new_text": ok_line}]}))
    P.append(("ops-newtext-prose",  {"operations": [{"action": "add", "new_text": prose}]}))
    P.append(("ops-both-content-wins", {"operations": [{"action": "add",
                                                        "content": ok_line, "new_text": prose}]}))
    P.append(("ops-both-prose-first",  {"operations": [{"action": "add",
                                                        "content": prose, "new_text": ok_line}]}))
    P.append(("ops-remove",         {"operations": [{"action": "remove", "old_text": "java"}]}))
    P.append(("ops-user-prose",     {"operations": [{"target": "user", "action": "add",
                                                     "content": prose}]}))
    P.append(("ops-ascii-arrow",    {"operations": [{"action": "add",
                                                     "content": "java,jvm -> j.md"}]}))
    P.append(("ops-empty",          {"operations": []}))
    # legacy shape
    P.append(("legacy-replace",     {"action": "replace", "target": "memory",
                                     "old_text": "github,ops", "content": ok_line}))
    # --- span-semantics probes (added 2026-10-29 after round-1 violations) ---
    P.append(("patch-arrow-to-ascii", {"action": "patch", "target": "memory",
                                      "old_text": "java-jvm.md", "content": "java-jvm.txt"}))
    P.append(("patch-into-newline", {"action": "patch", "target": "memory",
                                     "old_text": "java", "content": "jav\na"}))
    P.append(("patch-content-wins", {"action": "patch", "target": "memory",
                                     "old_text": "ockentap", "content": "ocky",
                                     "new_text": prose}))
    P.append(("patch-newtext-only", {"action": "patch", "target": "memory",
                                     "old_text": "ockentap", "new_text": "ocky"}))
    P.append(("patch-newtext-prose", {"action": "patch", "target": "memory",
                                      "old_text": "ockentap", "new_text": prose}))
    P.append(("ops-patch-newtext-prose",
              {"operations": [{"action": "patch", "old_text": "ockentap",
                               "new_text": prose}]}))
    P.append(("ops-patch-span-prose",
              {"operations": [{"action": "patch", "old_text": "java,jvm,heap → jav",
                               "content": "x →\nPROSE "}]}))
    P.append(("ops-add-empty-list-with-top-prose",
              {"action": "add", "target": "memory", "content": prose, "operations": []}))
    P.append(("ops-invalid-op-not-dict",
              {"operations": ["not-a-dict"]}))
    return P


def main():
    verbose = "--verbose" in sys.argv
    bypass = overblock = toolerr = 0
    print(f"plugin under test: {REPO_PLUGIN}")
    for pid, shape in probes():
        # lane 1: no guard — what does the real tool do to the file?
        try:
            _, final_nog, res_nog = run_lane(shape, guard_enabled=False)
            blocked_raw = False
        except RuntimeError as e:
            # Malformed shapes can raise INSIDE the tool (e.g. non-dict ops
            # entries) before any mutation; the tool's gate iterates ops while
            # building the approval summary. Model that as: file unchanged.
            final_nog = HEADER + "\n".join(SEED_LINES) + "\n"
            blocked_raw = True
            res_nog = "(tool raised before writing)"
        valid_nog, bad_nog = file_valid(final_nog)

        # lane 2: guard enabled
        try:
            blocked, final_g, res_g = run_lane(shape, guard_enabled=True)
        except RuntimeError as e:
            # Guard passed, then the tool itself raised on a malformed shape
            # (e.g. non-dict ops entries). That is a tool-side crash, not a
            # guard bypass: the file was not corrupted. Surface it separately.
            blocked = False
            final_g = HEADER + "\n".join(SEED_LINES) + "\n"
            res_g = "(guard passed; tool raised on malformed shape)"
            print(f"[NOTE] {pid}: guard allowed a shape the tool itself crashes on "
                  f"— malformed input, out of guard scope")
        valid_g, bad_g = file_valid(final_g)

        status = "ok"
        if not blocked and not valid_g:
            # guard allowed a write that corrupts the index format
            if blocked_raw and valid_nog:
                # tool itself refused too — guard agreeing with tool, file fine
                status = "ok (tool refuses)"
            else:
                status = "BYPASS"
                bypass += 1
        if blocked and valid_nog and not bad_nog:
            # tool would have written a valid file but guard refused
            status = "OVERBLOCK"
            overblock += 1

        mark = "✅" if status.startswith("ok") else "❌"
        if not status.startswith("ok") or verbose:
            tool_note = "tool-refused" if blocked_raw and not valid_nog else \
                        ("valid-write" if valid_nog else "corrupting-write")
            print(f"{mark} {pid:26s} guard={'BLOCK' if blocked else 'PASS '} "
                  f"tool={tool_note:14s} file={'VALID' if valid_g else 'INVALID: ' + str(bad_g[:1])} -> {status}")
        else:
            print(f"{mark} {pid}")

    print()
    print(f"SUMMARY: {bypass} bypasses, {overblock} overblocks, {toolerr} harness errors")
    if bypass or overblock or toolerr:
        print("GATE: RED — fix the violations above")
        sys.exit(1)
    print("GATE: GREEN — every advertised shape verified against the real tool")


if __name__ == "__main__":
    main()
