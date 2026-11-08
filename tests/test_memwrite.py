"""memwrite: the plan applies, normalises, validates, and never touches the index template."""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "memwrite.py"
VERIFY = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "verify_index.py"

HEADER = (
    "# Dynamic Memory Index — dynmem\n"
    "# All memories are located in: <dir>\n"
    "keyword,keyword,keyword → file.md\n"
    "alpha beta gamma delta epsilon → hub.md\n"
)


def load():
    spec = importlib.util.spec_from_file_location("memwrite_mod", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def store(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "MEMORY.md").write_text(HEADER, encoding="utf-8")
    (tmp_path / "hub.md").write_text(
        "one two three four five → leaf.md\nsix seven eight nine ten → other.md\n", encoding="utf-8")
    (tmp_path / "leaf.md").write_text("# Leaf\nthe first memory\n", encoding="utf-8")
    (tmp_path / "other.md").write_text("# Other\nthe second memory\n", encoding="utf-8")
    return tmp_path


NEW_PLAN = {
    "mode": "new",
    "neuron": {"name": "dryer.md", "lines": ["heat fan sensor chamber → dryer-hardware.md"]},
    "engrams": [{"name": "dryer-hardware.md",
                 "content": "# Dryer hardware\nPart of: dryer.md.\n\nESP32, PTC heater, fan.\n"}],
    "index_line": "dryer filament heat petg nylon → dryer.md",
}


def test_new_plan_applies_and_validates(tmp_path):
    m = load()
    s = store(tmp_path)
    m.apply_plan(s, NEW_PLAN)
    m.normalise(s)
    r = subprocess.run([sys.executable, str(VERIFY), str(s / "MEMORY.md"), "--memdir", str(s),
                        "--tree", "--keywords"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    assert (s / "dryer.md").exists() and (s / "dryer-hardware.md").exists()
    assert (s / "MEMORY.md").read_text().count("→ dryer.md") == 1


def test_index_template_is_untouched(tmp_path):
    m = load()
    s = store(tmp_path)
    m.apply_plan(s, NEW_PLAN)
    m.normalise(s)
    assert "keyword,keyword,keyword → file.md" in (s / "MEMORY.md").read_text()


def test_colliding_keyword_is_deduped_and_topped_up(tmp_path):
    m = load()
    s = store(tmp_path)
    plan = dict(NEW_PLAN, index_line="alpha filament heat petg nylon → dryer.md")
    m.apply_plan(s, plan)
    m.normalise(s)
    lines = [l for l in (s / "MEMORY.md").read_text().splitlines() if l.endswith("→ dryer.md")]
    kws = lines[0].split("→")[0].split()
    assert kws.count("alpha") == 0, "alpha belongs to the hub line"
    assert len(kws) >= 5


def test_update_rewrites_without_touching_index(tmp_path):
    m = load()
    s = store(tmp_path)
    before = (s / "MEMORY.md").read_text()
    m.apply_plan(s, {"mode": "update", "target": "leaf.md",
                     "content": "# Leaf\nthe first memory, corrected\n"})
    assert "corrected" in (s / "leaf.md").read_text()
    assert (s / "MEMORY.md").read_text() == before


def test_update_of_missing_target_is_refused(tmp_path):
    m = load()
    s = store(tmp_path)
    try:
        m.apply_plan(s, {"mode": "update", "target": "nope.md", "content": "# x\n"})
    except SystemExit as e:
        assert e.code == 3
    else:
        raise AssertionError("expected refusal")


def test_dry_run_writes_nothing(tmp_path):
    s = store(tmp_path)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(__import__("json").dumps(NEW_PLAN), encoding="utf-8")
    before = {p.name: p.read_text() for p in s.glob("*.md")}
    r = subprocess.run([sys.executable, str(SCRIPT), "--store", str(s), "--plan", str(plan_file),
                        "--dry-run"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    after = {p.name: p.read_text() for p in s.glob("*.md")}
    assert before == after
