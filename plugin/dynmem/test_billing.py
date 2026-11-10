# Tests for billing.py — the one-time "requests or tokens?" shape question.
#
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory.

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import billing


def _home(tmp_path: Path) -> Path:
    return tmp_path / "hermes"


def setup_function(_fn):
    billing.configure("")


def test_asks_once_until_answered(tmp_path):
    home = _home(tmp_path)
    text = billing.setup_context(home)
    assert text and "fewer requests" in text and "fewer tokens" in text

    billing.mark_asked(home)
    assert billing.setup_context(home) is None  # asked once, never nag again


def test_a_configured_profile_silences_the_question(tmp_path):
    home = _home(tmp_path)
    billing.configure("tokens")
    assert billing.setup_context(home) is None


def test_mode_line_is_stated_once_per_session(tmp_path):
    home = _home(tmp_path)
    billing.configure("tokens")
    first = billing.mode_context("s1", home)
    assert first and "tiered" in first
    assert billing.mode_context("s1", home) is None       # same session: silent
    assert billing.mode_context("s2", home) is not None   # new session: once more


def test_requests_profile_says_flat(tmp_path):
    home = _home(tmp_path)
    billing.configure("requests")
    line = billing.mode_context("s3", home)
    assert line and "flat" in line


def test_unknown_profile_is_treated_as_unset(tmp_path):
    home = _home(tmp_path)
    billing.configure("banana")
    assert billing.mode_context("s4", home) is None
    assert billing.setup_context(home)  # still unasked


def test_told_sessions_list_stays_bounded(tmp_path):
    home = _home(tmp_path)
    billing.configure("tokens")
    for i in range(60):
        billing.mode_context(f"s{i}", home)
    told = billing.load_state(home)["told"]
    assert len(told) == 50
    assert told[-1] == "s59"
