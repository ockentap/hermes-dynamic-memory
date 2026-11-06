"""Format guard: the 5-20 keyword band and the Unicode-only arrow, on every path.

Found while verifying the installed plugin (2026-11-03):
  * `_validate_arrow_target` accepted 1-25 keywords while every message, the
    README and the skill say 5-20, so a 21-keyword line passed.
  * The single-op (older Hermes) path treated `kw,kw -> file.md` as "keywords,
    no arrow" and passed it as an entry; only the operations[] path refused the
    ASCII arrow.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

PLUGIN_PATH = pathlib.Path(__file__).resolve().parents[1] / "plugin" / "dynmem" / "plugin.py"

HEADER = (
    "# Dynamic Memory Index\n"
    "A keyword routing table, not the knowledge base.\n"
    "keyword,keyword,keyword \u2192 file.md\n"
    "alpha,beta,gamma,delta,epsilon \u2192 one.md\n"
)


@pytest.fixture
def shaper(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("dynmem_format_under_test", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    home = tmp_path / "hermes"
    (home / "memories").mkdir(parents=True)
    (home / "memories" / "MEMORY.md").write_text(HEADER, encoding="utf-8")
    monkeypatch.setattr(module, "_hermes_home", lambda: home)
    return module


def _add(module, content):
    return module.handle_pre_tool_call("memory", {"action": "add", "content": content})


def test_ascii_arrow_is_refused_on_the_single_op_path(shaper):
    result = _add(shaper, "alpha,beta,gamma,delta,epsilon -> alpha.md")
    assert result.get("action") == "block"
    assert "Wrong arrow" in result.get("message", "")


def test_too_many_keywords_is_refused(shaper):
    content = ",".join(f"kw{i}" for i in range(21)) + " \u2192 many.md"
    result = _add(shaper, content)
    assert result.get("action") == "block", result
    assert "21 keywords" in result.get("message", "")


def test_too_few_keywords_is_refused(shaper):
    result = _add(shaper, "alpha,beta \u2192 few.md")
    assert result.get("action") == "block", result


@pytest.mark.parametrize("count", [5, 20])
def test_band_edges_are_accepted(shaper, count):
    content = ",".join(f"kw{i}" for i in range(count)) + " \u2192 edge.md"
    assert _add(shaper, content) == {}


def test_the_21st_keyword_is_refused_with_a_count_message(shaper):
    """The 20 ceiling is the user's safeguard and must name itself, on every path."""
    content = ",".join(f"kw{i}" for i in range(21)) + " \u2192 many.md"
    single = _add(shaper, content)
    assert single.get("action") == "block", single
    assert "21 keywords" in single.get("message", "")
    assert "at most 20" in single.get("message", "")

    ops = shaper.handle_pre_tool_call("memory", {"operations": [
        {"action": "add", "target": "memory", "content": content},
    ]})
    assert ops.get("action") == "block", ops
    assert "21 keywords" in ops.get("message", "")


def test_patch_cannot_grow_a_line_past_twenty(shaper):
    twenty = ",".join(f"kw{i}" for i in range(20))
    (shaper._memory_dir() / "x.md").write_text("body", encoding="utf-8")
    shaper._memory_md().write_text(
        HEADER + f"{twenty} \u2192 x.md\n", encoding="utf-8"
    )
    result = shaper.handle_pre_tool_call("memory", {
        "action": "patch", "target": "memory",
        "old_text": "kw19", "content": "kw19,kw20",
    })
    assert result.get("action") == "block", result
    assert "21 keywords" in result.get("message", "")

