"""Stock-store safety: the header entry and the template cleanup.

Two review findings these pin down:
  * On the stock memory store the whole header is ONE §-joined entry, so a
    remove/replace/patch whose old_text lands anywhere inside it rewrites or
    deletes every header line at once. The guard now refuses that unless the
    user approved a rewrite.
  * Autoclean deleted any line whose target was one of the template's filenames,
    so a user's own entry for e.g. home-network.md disappeared on the next
    memory write. A line is only removed while it still matches the shipped
    template text exactly.
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
    spec = importlib.util.spec_from_file_location("memory_shaper_under_test", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    home = tmp_path / "hermes"
    (home / "memories").mkdir(parents=True)
    monkeypatch.setattr(module, "_hermes_home", lambda: home)
    return module, home


def _write(home, text: str):
    (home / "memories" / "MEMORY.md").write_text(text, encoding="utf-8")


def test_remove_inside_header_is_refused(shaper):
    module, home = shaper
    _write(home, HEADER)
    result = module.handle_pre_tool_call(
        "memory", {"action": "remove", "old_text": "A keyword routing table"}
    )
    assert result.get("action") == "block"
    assert "header" in result.get("message", "").lower()


def test_patch_inside_header_is_refused(shaper):
    module, home = shaper
    _write(home, HEADER)
    result = module.handle_pre_tool_call(
        "memory",
        {
            "operations": [
                {
                    "action": "patch",
                    "old_text": "A keyword routing table",
                    "content": "A keyword routing table, edited.",
                }
            ]
        },
    )
    assert result.get("action") == "block"
    assert "header" in result.get("message", "").lower()


def test_header_edit_allowed_with_rewrite_approval(shaper):
    module, home = shaper
    _write(home, HEADER)
    (home / "state").mkdir()
    (home / "state" / ".memory_shaper_rewrite_approved").touch()
    result = module.handle_pre_tool_call(
        "memory", {"action": "remove", "old_text": "A keyword routing table"}
    )
    assert result == {}


def test_entry_edit_still_passes(shaper):
    module, home = shaper
    _write(home, HEADER)
    result = module.handle_pre_tool_call(
        "memory",
        {
            "operations": [
                {
                    "action": "patch",
                    "old_text": "alpha,beta,gamma,delta,epsilon",
                    "content": "alpha,beta,gamma,delta,epsilon,zeta",
                }
            ]
        },
    )
    assert result == {}


def test_autoclean_drops_only_the_exact_template_line(shaper):
    module, home = shaper
    _write(
        home,
        "# Dynamic Memory Index\n"
        "TEMPLATE \u2014 placeholders below\n"
        "keyword,keyword,keyword \u2192 file.md\n"
        "network,router,wifi,dns,subnet,vpn,firewall \u2192 home-network.md\n"
        "my,home,router,setup,wifi,dns,vpn \u2192 home-network.md\n",
    )
    module._autoclean_template_lines()
    text = (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")
    assert "TEMPLATE \u2014" not in text
    assert "network,router,wifi,dns,subnet,vpn,firewall" not in text
    # The user's own line is about the same target file and must survive.
    assert "my,home,router,setup,wifi,dns,vpn \u2192 home-network.md" in text
    # The structural line is never touched.
    assert "keyword,keyword,keyword \u2192 file.md" in text


def test_autoclean_keeps_template_line_when_the_file_exists(shaper):
    module, home = shaper
    (home / "memories" / "home-network.md").write_text("body", encoding="utf-8")
    _write(
        home,
        "# Dynamic Memory Index\n"
        "keyword,keyword,keyword \u2192 file.md\n"
        "network,router,wifi,dns,subnet,vpn,firewall \u2192 home-network.md\n",
    )
    module._autoclean_template_lines()
    text = (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")
    assert "network,router,wifi,dns,subnet,vpn,firewall \u2192 home-network.md" in text
