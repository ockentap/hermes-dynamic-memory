"""v1.7.0: ## Related edge validation in scripts/verify_index.py.

The block is the "webring" between topic files: at most five conditional links,
each of which the agent follows only when its condition matches. The checks have
to reject rot (missing targets, self links, run-away blocks, vague conditions)
and warn on the shapes that cause ping-pong reads (reciprocal edges, cycles).
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "verify_index.py"

INDEX = (
    "# Dynamic Memory Index — dynmem\n"
    "# All memories are located in: /tmp/memories\n"
    "keyword,keyword,keyword → file.md\n"
    "cooking,recipes,kitchen,food,dinner → recipes.md\n"
    "pasta,lasagna,oven,baking,tray → lasagna.md\n"
    "wine,cellar,bottles,vintage,storage → cellar.md\n"
)


@pytest.fixture
def verify():
    spec = importlib.util.spec_from_file_location("verify_index_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _memdir(tmp_path, related):
    """Write recipes.md (with *related* appended), lasagna.md, cellar.md and the index."""
    (tmp_path / "recipes.md").write_text("# Recipes\n\n- Pasta water must be salty.\n\n" + related,
                                         encoding="utf-8")
    (tmp_path / "lasagna.md").write_text("# Lasagna\n\n- Last time the béchamel broke.\n", encoding="utf-8")
    (tmp_path / "cellar.md").write_text("# Cellar\n\n- Reds above 18 C.\n", encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text(INDEX, encoding="utf-8")
    return tmp_path


def test_valid_block_counts_edges(verify, tmp_path):
    memdir = _memdir(tmp_path, "## Related\n"
                              "- when the user is cooking lasagna specifically → lasagna.md\n")
    onfile = {"recipes.md", "lasagna.md", "cellar.md"}
    ok, bad, warn = verify.check_related(str(memdir), onfile)
    assert (ok, bad, warn) == (1, [], [])


def test_missing_target_fails(verify, tmp_path):
    memdir = _memdir(tmp_path, "## Related\n- when the user asks about a dish → missing.md\n")
    ok, bad, warn = verify.check_related(str(memdir), {"recipes.md", "lasagna.md"})
    assert ok == 0 and len(bad) == 1
    assert "RELATED TARGET MISSING" in bad[0][2]


def test_self_link_fails(verify, tmp_path):
    memdir = _memdir(tmp_path, "## Related\n- when the user asks about recipes again → recipes.md\n")
    ok, bad, _ = verify.check_related(str(memdir), {"recipes.md", "lasagna.md"})
    assert ok == 0 and "RELATED SELF LINK" in bad[0][2]


def test_too_many_edges_fails(verify, tmp_path):
    block = "## Related\n" + "".join(
        f"- when the user asks about dish number {i} → lasagna.md\n" for i in range(6))
    memdir = _memdir(tmp_path, block)
    ok, bad, _ = verify.check_related(str(memdir), {"recipes.md", "lasagna.md"})
    assert any("TOO MANY RELATED EDGES" in b[2] for b in bad)


def test_vague_condition_fails(verify, tmp_path):
    memdir = _memdir(tmp_path, "## Related\n- when cooking → lasagna.md\n")
    ok, bad, _ = verify.check_related(str(memdir), {"recipes.md", "lasagna.md"})
    assert any("CONDITION TOO VAGUE" in b[2] for b in bad)


def test_non_edge_bullet_fails(verify, tmp_path):
    memdir = _memdir(tmp_path, "## Related memories\n- see also lasagna.md\n")
    ok, bad, _ = verify.check_related(str(memdir), {"recipes.md", "lasagna.md"})
    assert any("NOT AN EDGE" in b[2] for b in bad)


def test_reciprocal_edge_warns(verify, tmp_path):
    memdir = _memdir(tmp_path, "## Related\n- when the user is cooking lasagna → lasagna.md\n")
    (tmp_path / "lasagna.md").write_text(
        "# Lasagna\n\n## Related\n- when the user wants the recipe index → recipes.md\n",
        encoding="utf-8")
    ok, bad, warn = verify.check_related(str(memdir), {"recipes.md", "lasagna.md"})
    assert ok == 2 and not bad
    assert any("RECIPROCAL" in w[1] for w in warn)


def test_cycle_warns(verify, tmp_path):
    memdir = _memdir(tmp_path, "## Related\n- when the user is cooking lasagna → lasagna.md\n")
    (tmp_path / "lasagna.md").write_text(
        "# Lasagna\n\n## Related\n- when the user asks about wine with it → cellar.md\n",
        encoding="utf-8")
    (tmp_path / "cellar.md").write_text(
        "# Cellar\n\n## Related\n- when the user is planning a dinner menu → recipes.md\n",
        encoding="utf-8")
    ok, bad, warn = verify.check_related(str(memdir), {"recipes.md", "lasagna.md", "cellar.md"})
    assert not bad
    assert any("RELATED CYCLE" in w[1] for w in warn)


def test_plain_related_list_is_not_an_edge_block(verify, tmp_path):
    """Live topic files already carry `## Related` link lists — never fail those."""
    memdir = _memdir(tmp_path, "## Related\n"
                              "- `lasagna.md` — notes from last time\n"
                              "- `cellar.md` — wine pairings\n")
    ok, bad, warn = verify.check_related(str(memdir), {"recipes.md", "lasagna.md", "cellar.md"})
    assert (ok, bad, warn) == (0, [], [])


def test_canonical_heading_is_strict(verify, tmp_path):
    """`## Related memories` opts the block in, so a plain link inside it fails."""
    memdir = _memdir(tmp_path, "## Related memories\n- see also lasagna.md\n")
    ok, bad, _ = verify.check_related(str(memdir), {"recipes.md", "lasagna.md"})
    assert ok == 0 and any("NOT AN EDGE" in b[2] for b in bad)


def test_no_block_is_fine(verify, tmp_path):
    memdir = _memdir(tmp_path, "")
    ok, bad, warn = verify.check_related(str(memdir), {"recipes.md", "lasagna.md"})
    assert (ok, bad, warn) == (0, [], [])


def test_cli_exit_code_reflects_related_failures(tmp_path):
    """End to end: a bad Related block must make the validator exit 1."""
    memdir = _memdir(tmp_path, "## Related\n- when the user asks about a dish → missing.md\n")
    idx = memdir / "MEMORY.md"
    good = subprocess.run([sys.executable, str(SCRIPT), str(idx)], capture_output=True, text=True)
    assert good.returncode == 1, good.stdout
    assert "RELATED TARGET MISSING" in good.stdout
    assert "related edges OK" in good.stdout

    (memdir / "recipes.md").write_text("# Recipes\n\n- Pasta water must be salty.\n", encoding="utf-8")
    clean = subprocess.run([sys.executable, str(SCRIPT), str(idx)], capture_output=True, text=True)
    assert clean.returncode == 0, clean.stdout
