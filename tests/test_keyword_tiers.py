"""Per-tier keyword lines: verify_index.py --keywords.

Every neuron carries its own keyword line, 5-20 keywords, the first five locked
to the optimizer. Keywords are unique WITHIN a tier and may repeat ACROSS tiers,
so a synapse may reuse its index line's words by design. The check is opt-in so a
store written before the rule keeps validating clean.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "verify_index.py"

HEADER = (
    "# Dynamic Memory Index — dynmem\n"
    "# All memories are located at: /tmp/memories\n"
    "keyword,keyword,keyword → file.md\n"
)


def _run(memdir, *args):
    return subprocess.run([sys.executable, str(SCRIPT), str(memdir / "MEMORY.md"), *args],
                          capture_output=True, text=True)


def _store(tmp_path, files, lines):
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


KW = "keywords: alpha,beta,gamma,delta,epsilon\n"


def test_tier_two_headers_pass(tmp_path):
    memdir = _store(
        tmp_path,
        {
            "one.md": KW + "# One\n",
            "two.md": "keywords: zeta,eta,theta,iota,kappa\n# Two\n",
        },
        ["alpha,one,first,only,single → one.md",
         "zeta,two,second,pair,double → two.md"],
    )
    r = _run(memdir, "--keywords")
    assert r.returncode == 0, r.stdout
    assert "2 headers" in r.stdout
    assert "0 collisions" in r.stdout
    assert "tier(s)" in r.stdout


def test_missing_header_fails(tmp_path):
    memdir = _store(tmp_path, {"one.md": "# One\nno keywords here\n"},
                    ["alpha,one,first,only,single → one.md"])
    r = _run(memdir, "--keywords")
    assert r.returncode == 1
    assert "NO KEYWORD LINE" in r.stdout


def test_keyword_line_must_be_first(tmp_path):
    memdir = _store(tmp_path, {"one.md": "# One\n\n" + KW},
                    ["alpha,one,first,only,single → one.md"])
    r = _run(memdir, "--keywords")
    assert r.returncode == 1
    assert "KEYWORD LINE NOT FIRST" in r.stdout


def test_twenty_one_keywords_fails(tmp_path):
    kws = ",".join(f"k{i}" for i in range(21))
    memdir = _store(tmp_path, {"one.md": f"keywords: {kws}\n# One\n"},
                    ["alpha,one,first,only,single → one.md"])
    r = _run(memdir, "--keywords")
    assert r.returncode == 1
    assert "KEYWORD COUNT 21 outside" in r.stdout


def test_duplicate_in_line_fails(tmp_path):
    memdir = _store(tmp_path, {"one.md": "keywords: alpha,beta,gamma,delta,alpha\n# One\n"},
                    ["zeta,one,first,only,single → one.md"])
    r = _run(memdir, "--keywords")
    assert r.returncode == 1
    assert "DUPLICATE KEYWORDS IN LINE" in r.stdout


def test_marker_on_a_neuron_line_fails(tmp_path):
    memdir = _store(tmp_path, {"one.md": "keywords: !!alpha,beta,gamma,delta\n# One\n"},
                    ["zeta,one,first,only,single → one.md"])
    r = _run(memdir, "--keywords")
    assert r.returncode == 1
    assert "MARKER IS INDEX-ONLY" in r.stdout


def test_keyword_repeats_across_tiers_are_allowed(tmp_path):
    # 'alpha' is a T1 keyword and appears again in the T2 header.
    memdir = _store(tmp_path, {"one.md": KW + "# One\n"},
                    ["alpha,one,first,only,single → one.md"])
    r = _run(memdir, "--keywords")
    assert r.returncode == 0, r.stdout
    assert "0 collisions" in r.stdout


def test_collision_on_two_index_lines_fails(tmp_path):
    memdir = _store(
        tmp_path,
        {"one.md": KW + "# One\n",
         "two.md": "keywords: zeta,eta,theta,iota,kappa\n# Two\n"},
        ["alpha,one,first,only,single → one.md",
         "alpha,two,second,pair,double → two.md"],
    )
    r = _run(memdir, "--keywords")
    assert r.returncode == 1
    assert "KEYWORD NOT UNIQUE AT TIER 1" in r.stdout


def test_collision_between_two_headers_fails(tmp_path):
    memdir = _store(
        tmp_path,
        {"one.md": "keywords: shared,beta,gamma,delta,epsilon\n# One\n",
         "two.md": "keywords: shared,eta,theta,iota,kappa\n# Two\n"},
        ["alpha,one,first,only,single → one.md",
         "zeta,two,second,pair,double → two.md"],
    )
    r = _run(memdir, "--keywords")
    assert r.returncode == 1
    assert "KEYWORD NOT UNIQUE AT TIER 2" in r.stdout


def test_check_is_opt_in(tmp_path):
    """Without --keywords the same headerless store still validates clean."""
    memdir = _store(tmp_path, {"one.md": "# One\n"},
                    ["alpha,one,first,only,single → one.md"])
    r = _run(memdir)
    assert r.returncode == 0, r.stdout
