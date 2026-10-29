# === NEW: operations[] support (2026-10-29 fix per teknium1 review) ===

def test_operations_empty_bodies():
    """Empty-content ops in a batch should PASS (already filtered remove/user above)."""
    args = {
        "action": "add",
        "operations": [
            {"action": "add", "content": ""},
            {"action": "patch", "content": ""},
        ]
    }
    result = handle_pre_tool_call("memory", args)
    assert result == {}, f"Expected passthrough for empty ops, got {result}"

def test_operations_single_arrow():
    """A single valid arrow operation should PASS."""
    args = {
        "operations": [
            {"action": "add", "content": "java,jvm → java-jvm.md"},
        ]
    }
    result = handle_pre_tool_call("memory", args)
    assert result == {}, f"Expected passthrough for valid arrow op, got {result}"

def test_operations_bad_prose():
    """Prose in an operations[] entry should be BLOCKED."""
    args = {
        "operations": [
            {"action": "add", "content": "This is just regular English text with no commas at all"},
        ]
    }
    result = handle_pre_tool_call("memory", args)
    assert result.get("action") == "block", f"Expected block for prose in operations[], got {result}"
    assert "human-language prose" in result.get("message", ""), "Message should mention prose"

def test_operations_bad_arrow():
    """Malformed arrow in operations[] should be BLOCKED."""
    args = {
        "operations": [
            {"action": "add", "content": "this is prose → not_valid"},
        ]
    }
    result = handle_pre_tool_call("memory", args)
    assert result.get("action") == "block", f"Expected block for malformed arrow, got {result}"
    assert "Malformed index line" in result.get("message", ""), f"Wrong message: {result.get('message', '')[:80]}"

def test_operations_verbose():
    """Verbose content in operations[] should be BLOCKED."""
    verbose_text = "a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z " * 3  # > 140 chars
    args = {
        "operations": [
            {"action": "add", "content": verbose_text},
        ]
    }
    result = handle_pre_tool_call("memory", args)
    assert result.get("action") == "block", f"Expected block for verbose ops, got {result}"
    msg_lower = result.get("message", "").lower()
    assert "verbose" in msg_lower or "verbosity" in msg_lower, f"Should mention verbosity: {result.get('message', '')[:100]}"

def test_operations_remove_still_passes():
    """Remove operations should always PASS regardless of content."""
    args = {
        "operations": [
            {"action": "remove", "old_text": "anything at all"},
        ]
    }
    result = handle_pre_tool_call("memory", args)
    assert result == {}, f"Expected passthrough for remove op, got {result}"

def test_operations_user_still_passes():
    """User-targeted operations should always PASS."""
    args = {
        "operations": [
            {"target": "user", "action": "add", "content": "any prose at all, with no keywords whatsoever"},
        ]
    }
    result = handle_pre_tool_call("memory", args)
    assert result == {}, f"Expected passthrough for user ops, got {result}"

def test_operations_mixed_valid_invalid():
    """First invalid op should stop the batch — first failure wins."""
    args = {
        "operations": [
            {"action": "add", "content": "valid,keywords → file.md"},
            {"action": "add", "content": "prose without any structure at all here"},
        ]
    }
    result = handle_pre_tool_call("memory", args)
    assert result.get("action") == "block", f"Expected block on second invalid op, got {result}"

def test_operations_ascii_arrow():
    """ASCII arrow in operations[] should be rejected."""
    args = {
        "operations": [
            {"action": "add", "content": "java -> /wrong/path.md"},
        ]
    }
    result = handle_pre_tool_call("memory", args)
    assert result.get("action") == "block", f"Expected block for ASCII arrow, got {result}"
    assert "Wrong arrow" in result.get("message", ""), f"Should mention wrong arrow: {result.get('message', '')[:80]}"


if __name__ == "__main__":
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from memory_shaper.plugin import handle_pre_tool_call
    print("Running new operations[] tests...")
    import traceback
    passed = 0
    failed = 0
    for name in sorted(dir()):
        if name.startswith("test_"):
            try:
                globals()[name]()
                print(f"  [PASS] {name}")
                passed += 1
            except AssertionError as e:
                print(f"  [FAIL] {name}: {e}")
                failed += 1
            except Exception as e:
                print(f"  [ERR]  {name}: {e}")
                traceback.print_exc()
                failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
