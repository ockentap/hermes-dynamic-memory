"""v1.7.0: the single absolute memories-path header.

The line has to exist exactly once, has to be filled by the plugin (the path is
per-profile and cannot ship in the template), and must never rewrite a store
that is not a dynmem index. These tests pin all of that, plus the idempotence
that keeps pre_llm_call from writing on every turn.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

PLUGIN_PATH = pathlib.Path(__file__).resolve().parents[1] / "plugin" / "memory-shaper" / "plugin.py"

INDEX_BODY = (
    "# Dynamic Memory Index — dynmem\n"
    "A keyword routing table, not the knowledge base.\n"
    "keyword,keyword,keyword → file.md\n"
    "alpha,beta,gamma,delta,epsilon → one.md\n"
    "zeta,eta,theta,iota,kappa → two.md\n"
)

STOCK_BODY = (
    "I prefer dark mode and short answers.\n"
    "§\n"
    "The user works in Sarajevo.\n"
)


@pytest.fixture
def shaper(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("memory_shaper_path_header_under_test", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    home = tmp_path / "hermes"
    memdir = home / "memories"
    memdir.mkdir(parents=True)
    monkeypatch.setattr(module, "_hermes_home", lambda: home)
    monkeypatch.delenv("MEMORY_SHAPER_NO_PATH_HEADER", raising=False)
    return module, home, memdir


def _write(memdir, body):
    (memdir / "MEMORY.md").write_text(body, encoding="utf-8")


def _path_lines(text):
    return [l for l in text.splitlines() if l.startswith("# All memories are located in:")]


def test_inserts_after_title_and_is_idempotent(shaper):
    module, home, memdir = shaper
    _write(memdir, INDEX_BODY)

    assert module.ensure_memory_path_header() is True
    text = (memdir / "MEMORY.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0].startswith("# Dynamic Memory Index")
    assert lines[1] == f"# All memories are located in: {memdir}"
    assert len(_path_lines(text)) == 1
    # Everything else is preserved, including the template line and both entries.
    assert "keyword,keyword,keyword → file.md" in text
    assert "alpha,beta,gamma,delta,epsilon → one.md" in text
    assert text.endswith("\n")

    # Second call is a no-op: pre_llm_call must not rewrite every turn.
    assert module.ensure_memory_path_header() is False
    assert (memdir / "MEMORY.md").read_text(encoding="utf-8") == text


def test_stock_store_is_never_touched(shaper):
    module, home, memdir = shaper
    _write(memdir, STOCK_BODY)
    assert module.ensure_memory_path_header() is False
    assert (memdir / "MEMORY.md").read_text(encoding="utf-8") == STOCK_BODY


def test_missing_file_is_a_noop(shaper):
    module, home, memdir = shaper
    assert module.ensure_memory_path_header() is False
    assert not (memdir / "MEMORY.md").exists()


def test_stale_path_is_rewritten_in_place(shaper):
    module, home, memdir = shaper
    stale = "# Dynamic Memory Index — dynmem\n# All memories are located in: /old/place/memories\n" + \
            "keyword,keyword,keyword → file.md\nalpha,beta,gamma,delta,epsilon → one.md\n"
    _write(memdir, stale)
    assert module.ensure_memory_path_header() is True
    text = (memdir / "MEMORY.md").read_text(encoding="utf-8")
    assert f"# All memories are located in: {memdir}" in text
    assert "/old/place/memories" not in text
    assert len(_path_lines(text)) == 1


def test_backup_slot_is_written_once(shaper):
    module, home, memdir = shaper
    _write(memdir, INDEX_BODY)
    assert module.ensure_memory_path_header() is True
    backup = home / "state" / "memory-header-backup.md"
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == INDEX_BODY
    # A second migration (stale path) must not clobber the original backup.
    backup.write_text("SENTINEL", encoding="utf-8")
    text = (memdir / "MEMORY.md").read_text(encoding="utf-8")
    (memdir / "MEMORY.md").write_text(text.replace(str(memdir), "/moved"), encoding="utf-8")
    assert module.ensure_memory_path_header() is True
    assert backup.read_text(encoding="utf-8") == "SENTINEL"


def test_template_placeholder_is_replaced(shaper):
    """The shipped template carries <MEMORIES_DIR>; the first run must replace it."""
    module, home, memdir = shaper
    body = INDEX_BODY.replace(
        "# Dynamic Memory Index — dynmem\n",
        "# Dynamic Memory Index — dynmem\n# All memories are located in: <MEMORIES_DIR>\n")
    _write(memdir, body)
    assert module.ensure_memory_path_header() is True
    text = (memdir / "MEMORY.md").read_text(encoding="utf-8")
    assert "<MEMORIES_DIR>" not in text
    assert len(_path_lines(text)) == 1
    assert f"# All memories are located in: {memdir}" in text


def test_env_kill_switch(shaper, monkeypatch):
    module, home, memdir = shaper
    _write(memdir, INDEX_BODY)
    monkeypatch.setenv("MEMORY_SHAPER_NO_PATH_HEADER", "1")
    assert module.ensure_memory_path_header() is False
    assert (memdir / "MEMORY.md").read_text(encoding="utf-8") == INDEX_BODY


def test_profile_path_is_resolved_per_call(shaper, monkeypatch, tmp_path):
    """A second profile in the same process must get its own path, not the first."""
    module, home, memdir = shaper
    _write(memdir, INDEX_BODY)
    assert module.ensure_memory_path_header() is True

    other = tmp_path / "hermes-other"
    (other / "memories").mkdir(parents=True)
    (other / "memories" / "MEMORY.md").write_text(INDEX_BODY, encoding="utf-8")
    monkeypatch.setattr(module, "_hermes_home", lambda: other)
    assert module.ensure_memory_path_header() is True
    text = (other / "memories" / "MEMORY.md").read_text(encoding="utf-8")
    assert f"# All memories are located in: {other / 'memories'}" in text
