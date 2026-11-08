"""Routers and engrams: verify_index.py --keywords.

A router is a table of route lines, `keyword,…,keyword → child.md`; the index is
the root router. An engram is content: it carries no keywords, because the line
that points at it already says what it is. Keywords are unique inside one table
and may repeat in another.
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

K5 = "alpha,beta,gamma,delta,epsilon"
K5B = "zeta,eta,theta,iota,kappa"


def _run(memdir, *args):
    return subprocess.run([sys.executable, str(SCRIPT), str(memdir / "MEMORY.md"), *args],
                          capture_output=True, text=True)


def _store(tmp_path, files, lines):
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def _router(*routes) -> str:
    return "\n".join(f"{kws} → {target}" for kws, target in routes) + "\n"


def test_router_and_engrams_pass(tmp_path):
    memdir = _store(
        tmp_path,
        {
            "hub.md": _router((K5, "one.md"), (K5B, "two.md")),
            "one.md": "# One\nthe first memory\n",
            "two.md": "# Two\nthe second memory\n",
        },
        [f"{K5} → hub.md"],
    )
    r = _run(memdir, "--tree", "--keywords")
    assert r.returncode == 0, r.stdout
    assert "0 collisions" in r.stdout


def test_route_line_needs_five_keywords(tmp_path):
    memdir = _store(
        tmp_path,
        {"hub.md": "alpha,beta,gamma → one.md\n", "one.md": "# One\n"},
        [f"{K5} → hub.md"],
    )
    r = _run(memdir, "--tree", "--keywords")
    assert r.returncode == 1
    assert "KEYWORD COUNT 3 outside" in r.stdout


def test_route_line_without_arrow_fails(tmp_path):
    body = _router((K5, "one.md"), (K5B, "two.md")) + "this line is prose\n"
    memdir = _store(
        tmp_path,
        {"hub.md": body, "one.md": "# One\n", "two.md": "# Two\n"},
        [f"{K5} → hub.md"],
    )
    r = _run(memdir, "--tree", "--keywords")
    assert r.returncode == 1
    assert "ROUTE LINE HAS NO ARROW" in r.stdout


def test_marker_on_a_route_line_fails(tmp_path):
    memdir = _store(
        tmp_path,
        {"hub.md": "!!alpha,beta,gamma,delta → one.md\n", "one.md": "# One\n"},
        [f"{K5} → hub.md"],
    )
    r = _run(memdir, "--tree", "--keywords")
    assert r.returncode == 1
    assert "MARKER IS INDEX-ONLY" in r.stdout


def test_duplicate_keyword_inside_one_table_fails(tmp_path):
    memdir = _store(
        tmp_path,
        {"hub.md": _router(("shared,beta,gamma,delta,epsilon", "one.md"),
                           ("shared,eta,theta,iota,kappa", "two.md")),
         "one.md": "# One\n", "two.md": "# Two\n"},
        [f"{K5} → hub.md"],
    )
    r = _run(memdir, "--tree", "--keywords")
    assert r.returncode == 1
    assert "KEYWORD NOT UNIQUE IN hub.md" in r.stdout


def test_same_keyword_in_different_tables_is_allowed(tmp_path):
    memdir = _store(
        tmp_path,
        {"a.md": _router(("shared,beta,gamma,delta,epsilon", "c1.md")),
         "b.md": _router(("shared,eta,theta,iota,kappa", "c2.md")),
         "c1.md": "# C1\n", "c2.md": "# C2\n"},
        [f"{K5} → a.md", f"{K5B} → b.md"],
    )
    r = _run(memdir, "--tree", "--keywords")
    assert r.returncode == 0, r.stdout
    assert "0 collisions" in r.stdout


def test_shared_engram_is_a_warning(tmp_path):
    memdir = _store(
        tmp_path,
        {"a.md": _router((K5, "shared.md"), ("aonly,alpha1,alpha2,alpha3,alpha4", "a-only.md")),
         "b.md": _router((K5B, "shared.md"), ("bonly,beta1,beta2,beta3,beta4", "b-only.md")),
         "shared.md": "# Shared\nthe memory\n",
         "a-only.md": "# A\n", "b-only.md": "# B\n"},
        [f"{K5} → a.md", f"{K5B} → b.md"],
    )
    r = _run(memdir, "--tree", "--keywords")
    assert r.returncode == 0, r.stdout
    assert "SHARED ENGRAM" in r.stdout


def test_five_station_chain_passes(tmp_path):
    e = {"n1.md": _router((K5, "n2.md")),
         "n2.md": _router((K5B, "n3.md")),
         "n3.md": _router(("k3a,k3b,k3c,k3d,k3e", "n4.md")),
         "n4.md": "# Engram\nthe memory\n"}
    memdir = _store(tmp_path, e, [f"{K5} → n1.md"])
    r = _run(memdir, "--tree", "--keywords")
    assert r.returncode == 0, r.stdout
    assert "tier 5/5" in r.stdout


def test_sixth_station_is_too_deep(tmp_path):
    e = {"n1.md": _router((K5, "n2.md")),
         "n2.md": _router((K5B, "n3.md")),
         "n3.md": _router(("k3a,k3b,k3c,k3d,k3e", "n4.md")),
         "n4.md": _router(("k4a,k4b,k4c,k4d,k4e", "n5.md")),
         "n5.md": "# E\n"}
    memdir = _store(tmp_path, e, [f"{K5} → n1.md"])
    r = _run(memdir, "--tree", "--keywords")
    assert r.returncode == 1
    assert "TREE TOO DEEP (tier 6 > 5)" in r.stdout
