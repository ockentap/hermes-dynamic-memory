"""split_memory.py: synapse/engram keyword lines in a split plan.

A plan may carry `synapse_keywords` for the file being split and `keywords` per
leaf; both are validated and written as each file's first line, and the
post-apply validator runs with --keywords when every file has one.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "split_memory.py"

INDEX = (
    "# Dynamic Memory Index — dynmem\n"
    "# All memories are located at: /tmp\n"
    "keyword,keyword,keyword → file.md\n"
    "alpha,beta,gamma,delta,epsilon → fat.md\n"
    "zeta,eta,theta,iota,kappa → other.md\n"
)

FAT = """# Fat project
intro line

## Goal
goal one
goal two

## Frame
frame one
frame two

## Quests
quest one
quest two
"""


def _store(tmp_path):
    (tmp_path / "fat.md").write_text(FAT, encoding="utf-8")
    (tmp_path / "other.md").write_text(
        "keywords: omega,sigma,tau,rho,phi\n# Other\ntext\n", encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text(INDEX, encoding="utf-8")
    return tmp_path


def _plan(tmp_path, leaves, synapse_keywords=None):
    body = {"hub_title": "Fat — routing card",
            "hub_intro": "Read this, then one leaf.",
            "leaves": leaves}
    if synapse_keywords is not None:
        body["synapse_keywords"] = synapse_keywords
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def test_keyword_lines_written_and_validated(tmp_path):
    mem = _store(tmp_path)
    plan = _plan(
        tmp_path,
        [
            {"file": "fat-goal.md", "start": 1, "end": 7,
             "keywords": "goal,plan,next,milestone,backlog",
             "when": "asking about the goal"},
            {"file": "fat-frame.md", "start": 8, "end": 14,
             "keywords": "frame,map,offset,npc,placement",
             "when": "working on the frame"},
        ],
        synapse_keywords="alpha,beta,gamma,delta,epsilon",
    )
    r = subprocess.run([sys.executable, str(SCRIPT), "--file", str(mem / "fat.md"),
                        "--plan", str(plan), "--apply"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    hub = (mem / "fat.md").read_text()
    assert hub.startswith("keywords: alpha,beta,gamma,delta,epsilon\n\n# Fat — routing card")
    goal = (mem / "fat-goal.md").read_text()
    assert goal.startswith("keywords: goal,plan,next,milestone,backlog\n# Fat Goal\nPart of: fat.md.")
    assert "tier(s)" in r.stdout


def test_marker_in_plan_is_refused(tmp_path):
    mem = _store(tmp_path)
    plan = _plan(tmp_path, [
        {"file": "fat-goal.md", "start": 1, "end": 14,
         "keywords": "!!goal,plan,next,milestone,backlog",
         "when": "asking about the goal"},
    ], synapse_keywords="alpha,beta,gamma,delta,epsilon")
    r = subprocess.run([sys.executable, str(SCRIPT), "--file", str(mem / "fat.md"),
                        "--plan", str(plan)], capture_output=True, text=True)
    assert r.returncode == 1
    assert "markers" in r.stderr


def test_plan_keyword_count_is_enforced(tmp_path):
    mem = _store(tmp_path)
    plan = _plan(tmp_path, [
        {"file": "fat-goal.md", "start": 1, "end": 14,
         "keywords": "goal,plan",  # below the floor of five
         "when": "asking about the goal"},
    ], synapse_keywords="alpha,beta,gamma,delta,epsilon")
    r = subprocess.run([sys.executable, str(SCRIPT), "--file", str(mem / "fat.md"),
                        "--plan", str(plan)], capture_output=True, text=True)
    assert r.returncode == 1
    assert "need 5-20" in r.stderr
