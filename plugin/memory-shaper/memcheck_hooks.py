# memcheck_hooks — the two hook adapters for memcheck
#
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
#
# `pre_llm_call` appends the tag to the wire copy of the user message only
# (agent/turn_context.py::build_api_messages — `messages` is untouched, so the
# tag never reaches SQLite). `transform_llm_output` runs BEFORE the assistant
# row is first persisted (agent/turn_finalizer.py::apply_llm_output_transform,
# #44239), so the stripped text is both what the user sees and what the next
# turn replays — the tag cannot leak into the corpus the keyword miner reads.
#
# Everything here is fail-open and silent: a broken monitor must never cost a
# reply.

from __future__ import annotations

import os
import time
from pathlib import Path

import memcheck

PLUGIN_ID = "memory-shaper"
_MAX_BODY_BYTES = 200_000


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def _enabled() -> bool:
    return os.environ.get("MEMCHECK_DISABLED", "").strip() not in {"1", "true", "yes"}


def _load_index(home: Path) -> tuple[dict[str, list[str]], list[str]]:
    index = home / "memories" / memcheck.INDEX_NAME
    try:
        text = index.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}, []
    return memcheck.parse_index(text), text.splitlines()


def _body(home: Path, name: str) -> str:
    p = home / "memories" / os.path.basename(name)
    try:
        if p.stat().st_size > _MAX_BODY_BYTES:
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                return fh.read(_MAX_BODY_BYTES)
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def pre_llm_call(session_id: str = "", user_message: str = "", conversation_history=None,
                 is_first_turn: bool = False, platform: str = "", model: str = "",
                 turn_id: str = "", **_kw):
    """Return {"context": tag} for the turns that should carry one, else None."""
    if not _enabled():
        return None
    if (platform or "").lower() in memcheck.SKIP_PLATFORMS:
        return None
    try:
        home = _hermes_home()
        message = user_message if isinstance(user_message, str) else ""
        turn = memcheck.human_turn(conversation_history, is_first_turn, message)
        state = memcheck.load_state(home)
        sess = memcheck.session_state(state, session_id or "default")
        memcheck.remember_message(sess, message)

        kind = memcheck.injection_for_turn(turn, sess)
        if kind == "1" and not memcheck.has_substance(message):
            kind = None
        if not kind:
            memcheck.save_state(home, {**state, session_id or "default": sess})
            return None

        sess["last_asked_turn"] = turn
        sess["asked_kind"] = kind
        existing = sess.get("asks")
        asks: dict = existing if isinstance(existing, dict) else {}
        asks[kind] = int(asks.get(kind) or 0) + 1
        sess["asks"] = asks
        memcheck.save_state(home, {**state, session_id or "default": sess})
        return {"context": memcheck.build_context(kind)}
    except Exception:
        return None


def transform_llm_output(response_text: str = "", session_id: str = "", platform: str = "",
                         model: str = "", turn_id: str = "", **_kw):
    """Strip the tag, validate its claims, log one sample. Returns None when absent."""
    if not _enabled():
        return None
    if (platform or "").lower() in memcheck.SKIP_PLATFORMS:
        return None
    if not isinstance(response_text, str) or "<mc" not in response_text.lower():
        return None
    try:
        visible, raw_tag, misplaced = memcheck.split_tag(response_text)
        sample = memcheck.parse_tag(raw_tag or "")

        home = _hermes_home()
        key = session_id or "default"
        state = memcheck.load_state(home)
        sess = memcheck.session_state(state, key)

        entries, _lines = _load_index(home)
        user_messages = list(sess.get("msgs") or [])
        used_files = (memcheck.split_targets(sess.get("last_opened"))
                      or memcheck.split_targets(sample.get("right")))
        sample["used_files"] = used_files

        bodies: dict[str, str] = {}
        for name in (memcheck.split_targets(sample.get("opened"))
                     + memcheck.split_targets(sample.get("rejected"))
                     + memcheck.split_targets(sample.get("wrong"))
                     + memcheck.split_targets(sample.get("right"))
                     + used_files):
            base = os.path.basename(name)
            if base in entries and base not in bodies:
                bodies[base] = _body(home, base)

        problems = memcheck.validate(sample, entries, bodies, user_messages)
        if misplaced:
            problems.append("text_after_tag")

        terms_source = user_messages[-1] if sample.get("verdict") == "wrong" and user_messages else (
            user_messages[-2] if len(user_messages) > 1 else (user_messages[-1] if user_messages else ""))
        target_for_terms = (memcheck.split_targets(sample.get("right")) or used_files
                            or memcheck.split_targets(sample.get("opened")) or [None])[0]
        terms = memcheck.prompt_terms(terms_source, entries, target=target_for_terms)

        record = {
            "ts": int(time.time()),
            "session": key,
            "turn_id": turn_id,
            "model": model,
            "platform": platform,
            "t": sample.get("t"),
            "opened": sample.get("opened"),
            "rejected": sample.get("rejected"),
            "verdict": sample.get("verdict"),
            "wrong": sample.get("wrong"),
            "right": sample.get("right"),
            "hook": sample.get("hook"),
            "fact": sample.get("fact"),
            "used_files": used_files,
            "terms": terms,
            "problems": problems,
            "user_tail": (user_messages[-1] if user_messages else "")[:400],
            "raw": (raw_tag or "")[:600],
        }
        memcheck.append_sample(home, record)

        if sample.get("t") == "1":
            sess["last_opened"] = sample.get("opened")
        if sample.get("t") == "2":
            sess["last_verdict"] = sample.get("verdict")
            sess["last_asked_turn"] = 0
        memcheck.save_state(home, {**state, key: sess})
        return visible
    except Exception:
        # Never leave the tag in front of the user because we failed to parse.
        try:
            visible, _raw, _m = memcheck.split_tag(response_text)
            return visible if visible != response_text else None
        except Exception:
            return None
