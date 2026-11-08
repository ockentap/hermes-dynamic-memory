"""memoptimizer — the idle "🧠 Memory Optimized" hook.

Records activity from pre_llm_call, and after 15 minutes with no message runs
`scripts/optimize.py` for the session: it summarises the new part of the
transcript and writes the facts through memwrite. A manual trigger file makes
the same run happen on demand:

    touch ~/.hermes/state/optimize.trigger

On success the plugin logs the line and, when platform actions are allowed, adds
a 🧠 reaction to the last message so the gateway shows that memory was updated.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import sys
import threading
import time

PLUGIN_ID = "memoptimizer"
IDLE_SECONDS = int(os.environ.get("MEMOPTIMIZER_IDLE_SECONDS", "900"))
POLL_SECONDS = int(os.environ.get("MEMOPTIMIZER_POLL_SECONDS", "20"))

STATE = pathlib.Path.home() / ".hermes" / "state"
ACTIVITY = STATE / "memoptimizer-activity.json"
TRIGGER = STATE / "optimize.trigger"
LOG = STATE / "memoptimizer.log"
STORE = pathlib.Path(os.environ.get("MEMOPTIMIZER_STORE",
                                   pathlib.Path.home() / ".hermes" / "profiles" / "vps" / "memories"))
OPTIMIZE = pathlib.Path("/home/media/hermes-dynamic-memory/scripts/optimize.py")

_log = logging.getLogger(PLUGIN_ID)
_started = False


def _log_line(line: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {line}\n")
    _log.info(line)


def _state() -> dict:
    try:
        return json.loads(ACTIVITY.read_text())
    except Exception:
        return {}


def _save(state: dict) -> None:
    ACTIVITY.parent.mkdir(parents=True, exist_ok=True)
    ACTIVITY.write_text(json.dumps(state))


def _run(session_id: str, context=None) -> None:
    if not session_id or not OPTIMIZE.exists():
        return
    env = dict(os.environ)
    env.setdefault("MEMOPTIMIZER_RUN", "1")
    try:
        r = subprocess.run([sys.executable, str(OPTIMIZE), "--store", str(STORE),
                            "--session", session_id, "--quiet"],
                           capture_output=True, text=True, timeout=600, env=env)
        line = (r.stdout.strip().splitlines() or [r.stderr.strip()[:200] or "no output"])[-1]
    except Exception as e:  # never break the gateway
        line = f"optimize failed: {e}"
    _log_line(line)
    if context is not None and "Optimized" in line:
        try:
            context.platform_actions.add_reaction("🧠")
        except Exception:
            pass


def _loop() -> None:
    while True:
        try:
            st = _state()
            last = float(st.get("last_activity", 0))
            session = st.get("session_id", "")
            done_for = st.get("optimized_at", 0)
            if TRIGGER.exists():
                TRIGGER.unlink(missing_ok=True)
                if session:
                    _run(session)
                    st = _state()
                    st["optimized_at"] = time.time()
                    _save(st)
            elif session and last and (time.time() - last) >= IDLE_SECONDS and done_for < last:
                _run(session)
                st = _state()
                st["optimized_at"] = time.time()
                _save(st)
        except Exception as e:
            _log_line(f"loop error: {e}")
        time.sleep(POLL_SECONDS)


def _on_message(session_id: str = "", user_message: str = "", **_kw):
    st = _state()
    st["session_id"] = session_id or st.get("session_id", "")
    st["last_activity"] = time.time()
    _save(st)
    return None


def register(ctx) -> None:
    global _started
    ctx.register_hook("pre_llm_call", _on_message)
    if not _started:
        _started = True
        threading.Thread(target=_loop, name="memoptimizer", daemon=True).start()
        _log_line("memoptimizer started (idle %ss)" % IDLE_SECONDS)
