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
    assert "KEYWORD NOT UNIQUE UNDER the index" in r.stdout


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
    assert "KEYWORD NOT UNIQUE UNDER the index" in r.stdout


def test_check_is_opt_in(tmp_path):
    """Without --keywords the same headerless store still validates clean."""
    memdir = _store(tmp_path, {"one.md": "# One\n"},
                    ["alpha,one,first,only,single → one.md"])
    r = _run(memdir)
    assert r.returncode == 0, r.stdout


def _hub(kw: str, *edges) -> str:
    body = f"keywords: {kw}\n# Hub\n\n## Related memories\n"
    return body + "\n".join(f"- when {c} → {t}" for c, t in edges) + "\n"


def test_same_keyword_under_different_parents_is_allowed(tmp_path):
    """Uniqueness is per routing table, not per depth."""
    memdir = _store(
        tmp_path,
        {
            "a.md": _hub("alpha,one,first,only,single",
                         ("the user asks about the first thing", "c1.md")),
            "b.md": _hub("zeta,two,second,pair,double",
                         ("the user asks about the second thing", "c2.md")),
            "c1.md": "keywords: shared,beta,gamma,delta,epsilon\n# C1\n",
            "c2.md": "keywords: shared,eta,theta,iota,kappa\n# C2\n",
        },
        ["alpha,one,first,only,single → a.md",
         "zeta,two,second,pair,double → b.md"],
    )
    r = _run(memdir, "--tree", "--keywords")
    assert r.returncode == 0, r.stdout
    assert "0 collisions" in r.stdout


def test_shared_engram_is_a_warning_not_an_error(tmp_path):
    """Two neurons may lead to the same engram."""
    memdir = _store(
        tmp_path,
        {
            "a.md": _hub("alpha,one,first,only,single",
                         ("the user asks about the first thing", "shared.md")),
            "b.md": _hub("zeta,two,second,pair,double",
                         ("the user asks about the second thing", "shared.md")),
            "shared.md": "keywords: shared,beta,gamma,delta,epsilon\n# Shared\n",
        },
        ["alpha,one,first,only,single → a.md",
         "zeta,two,second,pair,double → b.md"],
    )
    r = _run(memdir, "--tree", "--keywords")
    assert r.returncode == 0, r.stdout
    assert "SHARED ENGRAM" in r.stdout
