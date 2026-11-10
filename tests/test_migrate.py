# Tests for scripts/migrate.py — the flat-store -> neurons migration.
#
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory.

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import migrate  # noqa: E402

INDEX = """# Memory index
# One line per memory, keyword list then the Unicode arrow.

aklima klima android app tariff schedule cheap hours \u2192 aklima-android-app.md
electricity gas price kwh bojler heating epbih \u2192 energy-prices-bih.md
vaultwarden bitwarden password server admin account vault.kucni.ba rsa masterkey \u2192 vaultwarden.md
gold zlato debt dug kids djeca asia newborn gifts pokloni grams ledger bam cijena \u2192 gold-debt-kids.md
"""

BODIES = {
    "aklima-android-app.md": "# aKlima app\n\nThe AC app talks to the Pi over the tailnet.\n",
    "energy-prices-bih.md": "# Energy prices\n\nVT and MT tariffs for EPBiH; the boiler runs on cheap hours.\n",
    "vaultwarden.md": "# Vaultwarden\n\nSelf-hosted Bitwarden at vault.kucni.ba.\n",
    "gold-debt-kids.md": "# Gold debts\n\nGifts and debts tracked in grams.\n",
}

PLAN = {
    "domains": [
        {"synapse": "aklima-household.md",
         "keywords": ["aklima", "klima", "android", "electricity", "gas", "vt", "mt", "tariff"],
         "children": ["aklima-android-app.md", "energy-prices-bih.md"],
         "rationale": "AC control and the tariff that decides when it runs"},
        {"synapse": "selfhosted-infra.md",
         "keywords": ["vaultwarden", "bitwarden", "password", "server", "admin", "account"],
         "children": ["vaultwarden.md"],
         "rationale": "single child on purpose — the plan must be rejected"},
    ]
}


def _store(tmp_path: Path) -> Path:
    store = tmp_path / "home" / "memories"
    store.mkdir(parents=True)
    (store / "MEMORY.md").write_text(INDEX, encoding="utf-8")
    for name, body in BODIES.items():
        (store / name).write_text(body, encoding="utf-8")
    return store


def _plan(tmp_path: Path, plan: dict) -> Path:
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    return p


def _hashes(store: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(store.glob("*.md"))}


def _good_plan() -> dict:
    """A valid plan: two domains, no keyword shared inside one synapse table."""
    plan = json.loads(json.dumps(PLAN))
    plan["domains"][1]["children"].append("gold-debt-kids.md")
    plan["domains"][1]["keywords"] = ["vaultwarden", "bitwarden", "password", "server",
                                      "admin", "account", "gold", "zlato", "debt"]
    plan["domains"][0]["child_keywords"] = {
        "aklima-android-app.md": ["aklima", "klima", "android", "app", "tariff", "schedule", "cheap"],
        "energy-prices-bih.md": ["electricity", "gas", "price", "kwh", "bojler", "heating", "epbih"],
    }
    plan["domains"][1]["child_keywords"] = {
        "vaultwarden.md": ["vaultwarden", "bitwarden", "password", "server", "admin", "account", "rsa"],
        "gold-debt-kids.md": ["gold", "zlato", "debt", "dug", "kids", "djeca", "asia", "newborn", "gifts"],
    }
    return plan


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("DYNMEM_MIGRATION_HOME", str(tmp_path / "offsite"))
    store = _store(tmp_path)
    before = _hashes(store)
    rc = migrate.main(["--store", str(store), "--plan", str(_plan(tmp_path, _good_plan()))])
    assert rc == 0
    assert _hashes(store) == before
    assert not (store / "aklima-household.md").exists()


def test_single_child_domain_is_rejected(tmp_path):
    store = _store(tmp_path)
    rc = migrate.main(["--store", str(store), "--plan", str(_plan(tmp_path, PLAN))])
    assert rc == 2  # plan rejected before any write


def test_unknown_child_is_rejected(tmp_path):
    store = _store(tmp_path)
    plan = _good_plan()
    plan["domains"][0]["children"].append("ghost.md")
    rc = migrate.main(["--store", str(store), "--plan", str(_plan(tmp_path, plan))])
    assert rc == 2


def test_bad_keywords_are_rejected(tmp_path):
    store = _store(tmp_path)
    plan = _good_plan()
    plan["domains"][0]["keywords"] = ["OnlyThree", "words", "here"]
    rc = migrate.main(["--store", str(store), "--plan", str(_plan(tmp_path, plan))])
    assert rc == 2


def test_apply_collapses_the_index_and_keeps_content(tmp_path, monkeypatch):
    offsite = tmp_path / "offsite"
    monkeypatch.setenv("DYNMEM_MIGRATION_HOME", str(offsite))
    store = _store(tmp_path)
    before = _hashes(store)

    rc = migrate.main(["--store", str(store), "--plan", str(_plan(tmp_path, _good_plan())), "--apply"])
    assert rc == 0

    index_lines = [l for l in (store / "MEMORY.md").read_text(encoding="utf-8").splitlines()
                   if "\u2192" in l]
    assert len(index_lines) == 2                      # 4 flat lines -> 2 synapses
    assert (store / "aklima-household.md").exists()
    assert (store / "selfhosted-infra.md").exists()

    after = _hashes(store)
    for name, digest in before.items():
        if name in {"MEMORY.md"}:
            continue
        assert after[name] == digest, f"{name} content changed"

    runs = list((tmp_path / "home" / "memories-backup").iterdir())
    assert runs and (runs[0] / "MEMORY.md").exists()
    assert list(offsite.iterdir())                    # second copy exists
    run = list(offsite.iterdir())[0]
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["created"] == ["aklima-household.md", "selfhosted-infra.md"]
    assert len(manifest["moves"]) == 4


def test_undo_restores_the_store_byte_identical(tmp_path, monkeypatch):
    offsite = tmp_path / "offsite"
    monkeypatch.setenv("DYNMEM_MIGRATION_HOME", str(offsite))
    store = _store(tmp_path)
    before = _hashes(store)

    assert migrate.main(["--store", str(store), "--plan", str(_plan(tmp_path, _good_plan())), "--apply"]) == 0
    run = list(offsite.iterdir())[0]

    assert migrate.main(["--undo", str(tmp_path / "home" / "memories-backup" / run.name)]) == 0
    assert _hashes(store) == before
    assert not (store / "aklima-household.md").exists()


def test_undo_refuses_when_the_store_moved(tmp_path, monkeypatch):
    offsite = tmp_path / "offsite"
    monkeypatch.setenv("DYNMEM_MIGRATION_HOME", str(offsite))
    store = _store(tmp_path)
    assert migrate.main(["--store", str(store), "--plan", str(_plan(tmp_path, _good_plan())), "--apply"]) == 0
    run = list(offsite.iterdir())[0]
    (store / "later-memory.md").write_text("# later\n", encoding="utf-8")
    assert migrate.main(["--undo", str(tmp_path / "home" / "memories-backup" / run.name)]) == 1
