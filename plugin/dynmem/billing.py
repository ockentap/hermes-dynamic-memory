# billing.py — the one-time "requests or tokens?" profile question
#
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
#
# dynmem has two shapes and they trade one cost for the other:
#
#   requests -> a flat index. MEMORY.md is the whole store: one line per memory,
#               one read per recall. Cheapest in round-trips, most expensive in
#               resident tokens, and it stops scaling at roughly 50-60 memories.
#   tokens   -> the tiered store. index -> synapses -> engrams, a thin resident
#               block, 2-3 reads per recall. More requests, far fewer tokens,
#               and it scales to hundreds of memories.
#
# The question is asked once, on the first human turn after install, and the
# answer is recorded in the plugin's own settings tree
# (plugins.entries.dynmem.settings.profile) so later sessions and the setup skill
# read the same value. `state/dynmem/billing.json` only remembers that we asked
# and which sessions already got the one-line mode reminder — never the answer.
#
# Deliberately dependency-free and fail-open: a broken question must never cost
# a reply.

from __future__ import annotations

import json
import os
import time
from pathlib import Path

STATE_DIR = "state"
STATE_SUBDIR = "dynmem"
STATE_FILE = "billing.json"

PROFILES = ("requests", "tokens")

_SETUP_CONTEXT = (
    "[dynmem] One-time setup question — ask the user, then record the answer.\n"
    "Question: \"Optimize dynmem for fewer requests, or fewer tokens?\"\n"
    "  fewer requests -> flat index: MEMORY.md is the whole store, one line per memory, "
    "one read per recall, more tokens resident; stops scaling past ~50-60 memories.\n"
    "  fewer tokens   -> tiered index: index -> synapses -> engrams, 2-3 reads per recall, "
    "far fewer tokens; scales to hundreds.\n"
    "Record the answer with: hermes config set plugins.entries.dynmem.settings.profile "
    "requests|tokens\n"
    "Do not restructure the store before they answer. Ask once, in one short message."
)

_MODE_LINES = {
    "requests": "[dynmem] profile: requests (flat index — one line per memory, one read per "
                "recall, keep MEMORY.md under ~60 lines).",
    "tokens": "[dynmem] profile: tokens (tiered — index -> synapses -> engrams, 2-3 reads per "
              "recall, keep engrams small and let synapses carry the routing).",
}

# Set by plugin.register() from plugins.entries.dynmem.settings.profile.
_profile = ""


def configure(profile: str | None = None) -> None:
    """Record the configured profile (called once from register())."""
    global _profile
    if profile is not None:
        _profile = str(profile).strip().lower()


def profile() -> str:
    return _profile


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def state_path(home: Path | None = None) -> Path:
    return Path(home or _hermes_home()) / STATE_DIR / STATE_SUBDIR / STATE_FILE


def load_state(home: Path | None = None) -> dict:
    try:
        raw = json.loads(state_path(home).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def save_state(state: dict, home: Path | None = None) -> None:
    try:
        p = state_path(home)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass  # state is an optimisation; never break a turn for it


def setup_context(home: Path | None = None) -> str | None:
    """The question, until it has been asked once (or the profile is set)."""
    if _profile in PROFILES:
        return None
    if load_state(home).get("asked_at"):
        return None
    return _SETUP_CONTEXT


def mark_asked(home: Path | None = None) -> None:
    state = load_state(home)
    state["asked_at"] = int(time.time())
    save_state(state, home)


def mode_context(session_id: str = "", home: Path | None = None) -> str | None:
    """One line stating the configured shape, once per session."""
    if _profile not in PROFILES:
        return None
    key = str(session_id or "default")
    state = load_state(home)
    told = state.get("told")
    told = list(told) if isinstance(told, list) else []
    if key in told:
        return None
    told.append(key)
    state["told"] = told[-50:]  # bounded: a long-lived install meets many sessions
    save_state(state, home)
    return _MODE_LINES.get(_profile)
