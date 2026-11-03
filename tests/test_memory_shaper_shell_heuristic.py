"""Shell heuristic: a pipe or a semicolon is not a write to the index.

Regression for 2026-11-03: any command whose first word was a read-only tool and
that carried a shell operator was refused as "MEMORY.md is write-locked", with the
whole command reported as the detected path — so `grep -c ... agent.log;
grep ... | tail -3` could not run. Only a write vector aimed AT the index is
refused now; reading it through a pipe is allowed.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

PLUGIN_PATH = pathlib.Path(__file__).resolve().parents[1] / "plugin" / "memory-shaper" / "plugin.py"

HEADER = (
    "# Dynamic Memory Index\n"
    "A keyword routing table, not the knowledge base.\n"
    "keyword,keyword,keyword \u2192 file.md\n"
    "alpha,beta,gamma,delta,epsilon \u2192 one.md\n"
)


@pytest.fixture
def shaper(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("memory_shaper_shell_under_test", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    home = tmp_path / "hermes"
    (home / "memories").mkdir(parents=True)
    (home / "memories" / "MEMORY.md").write_text(HEADER, encoding="utf-8")
    monkeypatch.setattr(module, "_hermes_home", lambda: home)
    return module, home


def _terminal(module, cmd):
    return module.handle_pre_tool_call("terminal", {"command": cmd})


def test_read_pipes_and_chains_are_not_writes(shaper):
    module, home = shaper
    for cmd in (
        'grep -c "Memory optimization" /var/log/agent.log',
        'grep -i "Memory optimization" /var/log/agent.log | tail -3',
        'grep -n x /var/log/agent.log; grep -c y /var/log/agent.log',
        'grep -rn tools.override /home/u/.hermes/plugins/memory-shaper/plugin.yaml | head -5',
    ):
        assert _terminal(module, cmd) == {}, cmd


def test_write_vectors_aimed_at_the_index_still_block(shaper):
    module, home = shaper
    index = home / "memories" / "MEMORY.md"
    for cmd in (
        f"cat a | tee {index}",
        f"cat a >> {index}",
        f"sort -o {index} x",
        f"cat $({index})",
        f"grep x {index} | sed -i s/a/b/",
    ):
        result = _terminal(module, cmd)
        assert result.get("action") == "block", cmd


def test_reading_the_index_through_a_pipe_is_allowed(shaper):
    module, home = shaper
    index = home / "memories" / "MEMORY.md"
    assert _terminal(module, f"grep alpha {index} | head -3") == {}
