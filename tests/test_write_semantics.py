"""Write-time cross-line invariants — the defects that used to need a nightly cleaner.

A live store accumulated four kinds of damage while every individual write passed
the hook: two index lines for one file, one keyword routing to two files, an index
line whose target was never written, and a memory with both an index line and a
parent edge. All four are cross-line facts, and the guard only looked at one line
at a time. These tests pin the refusals at write time.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

PLUGIN_PATH = pathlib.Path(__file__).resolve().parents[1] / "plugin" / "dynmem" / "plugin.py"

ARROW = "\u2192"
INDEX_LINE = f"alpha beta gamma delta epsilon {ARROW} alpha.md"
PARENT_LINE = f"parent synapse routing table keyword {ARROW} parent.md"


@pytest.fixture
def store(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("dynmem_semantics_under_test", PLUGIN_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    home = tmp_path / "hermes"
    mem = home / "memories"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text(
        "# Memory index\n" + INDEX_LINE + "\n" + PARENT_LINE + "\n", encoding="utf-8")
    for name in ("alpha.md", "beta.md", "gamma.md", "child.md"):
        (mem / name).write_text(f"# {name}\n\nbody\n", encoding="utf-8")
    (mem / "parent.md").write_text(
        f"child one two three four five {ARROW} child.md\n", encoding="utf-8")
    monkeypatch.setattr(module, "_hermes_home", lambda: home)
    return module


def _add(module, content):
    return module.handle_pre_tool_call("memory", {"action": "add", "content": content})


def test_second_line_for_the_same_file_is_refused(store):
    result = _add(store, f"zeta eta theta iota kappa {ARROW} alpha.md")
    assert result.get("action") == "block", result
    assert "already has an index line" in result["message"]
    assert INDEX_LINE in result["message"]          # shows the line to edit instead


def test_keyword_already_taken_by_another_file_is_refused(store):
    result = _add(store, f"alpha zeta eta theta iota {ARROW} beta.md")
    assert result.get("action") == "block", result
    assert "'alpha'" in result["message"] and "alpha.md" in result["message"]


def test_target_that_was_never_written_is_refused(store):
    result = _add(store, f"ghost phantom spectre wraith shade {ARROW} ghost.md")
    assert result.get("action") == "block", result
    assert "does not exist" in result["message"]


def test_index_line_for_a_synapse_child_is_refused(store):
    result = _add(store, f"child one two three four {ARROW} child.md")
    assert result.get("action") == "block", result
    assert "already a child of parent.md" in result["message"]


def test_clean_add_still_passes(store):
    assert _add(store, f"fresh novel unused words here {ARROW} gamma.md") == {}


def test_replace_may_extend_the_same_line(store):
    result = store.handle_pre_tool_call("memory", {
        "action": "replace",
        "old_text": INDEX_LINE,
        "content": f"alpha beta gamma delta epsilon zeta {ARROW} alpha.md",
    })
    assert result == {}, result


def test_synapse_refuses_two_routes_to_one_child(store):
    path = str(store._memory_dir() / "parent.md")
    text = (f"child one two three four five {ARROW} child.md\n"
            f"other six seven eight nine ten {ARROW} child.md\n")
    problem = store._router_problem(path, text)
    assert problem and "already has a route in this table" in problem


def test_synapse_refuses_a_child_that_has_an_index_line(store):
    path = str(store._memory_dir() / "parent.md")
    text = f"alpha beta gamma delta epsilon {ARROW} alpha.md\n"
    problem = store._router_problem(path, text)
    assert problem and "already has an index line" in problem


def test_synapse_refuses_a_child_of_another_parent(store):
    mem = store._memory_dir()
    (mem / "other-parent.md").write_text(
        f"child one two three four five {ARROW} child.md\n", encoding="utf-8")
    (mem / "newchild.md").write_text("# new\n", encoding="utf-8")
    path = str(mem / "other-parent.md")
    text = (f"child one two three four five {ARROW} child.md\n"
            f"newchild six seven eight nine ten {ARROW} newchild.md\n")
    # child.md is already routed by parent.md, so this table may not claim it too
    problem = store._router_problem(path, text)
    assert problem and "already a child of parent.md" in problem


def test_engram_quoting_a_route_line_is_not_a_parent(store):
    """A memory that documents the format may contain a route-shaped line.

    Only pure routing tables are parents; counting prose-bearing engrams would
    block a lawful index add (the live store has 112 such files).
    """
    mem = store._memory_dir()
    (mem / "notes.md").write_text(
        "# notes\n\nExample of the format:\n"
        f"alpha beta gamma delta epsilon {ARROW} gamma.md\n\nMore prose here.\n",
        encoding="utf-8")
    assert _add(store, f"fresh novel unused words here {ARROW} gamma.md") == {}
