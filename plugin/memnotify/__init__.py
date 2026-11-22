"""memnotify — 🧠 status lines in chat whenever the agent touches memory.

    🧠 memory-x.md read
    🧠 Updating memory-y.md
    🧠 memory-z.md created

One short message per operation, sent as it happens: the user sees memory being
consulted and changed instead of having to trust a claim in the answer. Sends
through the live Telegram adapter on the gateway's own event loop; a plain
message, no reaction, no ledger entry.

`pre_tool_call` records whether the target file existed, so `write_file` can say
"created" vs "updated". Duplicates inside one turn (same session, turn and line)
are collapsed.
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import re
import sqlite3
import time

PLUGIN_ID = "memnotify"
PREFIX = "\U0001F9E0 "  # 🧠
LOG = pathlib.Path.home() / ".hermes" / "state" / "memnotify.log"

_log = logging.getLogger(PLUGIN_ID)
_seen: set[tuple[str, str, str]] = set()
_pending: dict[str, tuple[str, bool]] = {}   # tool_call_id -> (path, existed)
_missing_logged = False


def _log_line(line: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {line}\n")
    except Exception:
        pass
    _log.debug(line)


def _home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("HERMES_HOME") or (pathlib.Path.home() / ".hermes"))


def _stores() -> list[pathlib.Path]:
    home = _home()
    out = [home / "memories"]
    try:
        out += sorted((home / "profiles").glob("*/memories"))
    except Exception:
        pass
    return sorted({p.resolve() for p in out if p.parent.exists()})


def _in_store(path_text: str) -> pathlib.Path | None:
    if not path_text:
        return None
    try:
        path = pathlib.Path(path_text).expanduser().resolve()
    except Exception:
        return None
    for store in _stores():
        if path == store or store in path.parents:
            return path
    return None


def _paths_in_text(text: str) -> list[str]:
    """Memory filenames named literally inside a shell command or code blob."""
    if not text:
        return []
    found: set[str] = set()
    for store in _stores():
        prefix = str(store)
        for m in re.finditer(re.escape(prefix) + r"/?([A-Za-z0-9_.\-]+\.md)", text):
            found.add(m.group(1))
    return sorted(found)


_WRITE_HINT = re.compile(
    r"(^|[;&|]\s*|\s)(sed\s+-i|tee\b|truncate\b|rm\b|mv\b|cp\b|shutil\.(?:move|copy)|"
    r"open\([^)]*['\"][wa])", re.MULTILINE)


def _line_for(tool: str, args: dict, existed: bool | None) -> str | None:
    name = (tool or "").strip()
    if name == "memory":
        target = str(args.get("target") or "memory")
        return f"{PREFIX}{'USER.md' if target == 'user' else 'MEMORY.md'} updated"
    if name in {"execute_code", "terminal"}:
        # the store is often reached from a shell command or a code blob (cat /
        # grep / open()); without this the chat shows a python line instead of
        # the memory line the user asked for
        text = str(args.get("code") or args.get("command") or "")
        files = [f for f in _paths_in_text(text) if f != "MEMORY.md"]
        if not files:
            # a directory-wide grep names the store, not one file
            if any(str(store) in text for store in _stores()):
                return f"{PREFIX}memories searched"
            return None
        verb = "updated" if _WRITE_HINT.search(text) else "read"
        if len(files) == 1:
            return f"{PREFIX}{files[0]} {verb}"
        return f"{PREFIX}{len(files)} memory files {verb}"
    path = _in_store(str(args.get("path") or ""))
    if path is None:
        return None
    if name == "read_file":
        return f"{PREFIX}{path.name} read"
    if name == "patch":
        return f"{PREFIX}Updating {path.name}"
    if name == "write_file":
        return f"{PREFIX}{path.name} {'created' if existed is False else 'updated'}"
    return None


def _db_candidates() -> list[pathlib.Path]:
    home = _home()
    out = [home / "state.db"]
    try:
        out += sorted((home / "profiles").glob("*/state.db"))
    except Exception:
        pass
    return out


def _target(session_id: str) -> tuple[str, str | None] | None:
    """(chat_id, thread_id) for this session."""
    global _missing_logged
    for db in _db_candidates():
        if not db.exists():
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
            row = con.execute("select chat_id, thread_id from sessions where id=?", (session_id,)).fetchone()
            con.close()
        except Exception:
            continue
        if row and row[0]:
            return str(row[0]), (str(row[1]) if row[1] not in (None, "", "1") else None)
    if not _missing_logged:
        _missing_logged = True
        _log_line(f"no chat for session {session_id} (non-chat turn)")
    return None


def _telegram_adapter():
    try:
        from gateway.run import _gateway_runner_ref

        runner = _gateway_runner_ref()
    except Exception:
        return None, None
    if runner is None:
        return None, None
    loop = getattr(runner, "_gateway_loop", None)
    adapter = None
    try:
        from gateway.config import Platform

        resolve = getattr(runner, "_authorization_adapter", None)
        if callable(resolve):
            try:
                from hermes_cli.profiles import get_active_profile_name

                adapter = resolve(Platform.TELEGRAM, get_active_profile_name())
            except Exception:
                adapter = None
        if adapter is None:
            adapter = getattr(runner, "adapters", {}).get(Platform.TELEGRAM)
    except Exception:
        adapter = None
    return adapter, loop


def _send(chat_id: str, text: str, thread_id: str | None) -> None:
    adapter, loop = _telegram_adapter()
    if adapter is None or loop is None or not loop.is_running():
        _log_line(f"skip (no adapter/loop): {text}")
        return
    metadata: dict = {"_interim_send": True}
    if thread_id:
        metadata["thread_id"] = thread_id
    try:
        fut = asyncio.run_coroutine_threadsafe(adapter.send(chat_id, text, metadata=metadata), loop)
        result = fut.result(timeout=10)
        ok = getattr(result, "success", None)
        err = getattr(result, "error", None)
        _log_line(f"sent {chat_id}/{thread_id or '-'} {text!r} ok={ok}{'' if ok else f' err={err}'}")
    except Exception as exc:
        _log_line(f"send failed: {exc}")


def _tui_notice(session_id: str, text: str) -> None:
    """Same line on the TUI/desktop notice bus, only when that host is loaded.

    ``notification.show`` is what credits warnings and model-switch notices use.
    The callbacks module rebinds its emitter to the TUI server, so the call is
    made through it and only when it is already in ``sys.modules`` — importing
    the TUI server into a Telegram gateway just to try would be a side effect
    nobody asked for.
    """
    import sys

    try:
        ac = sys.modules.get("tui_gateway.agent_callbacks")
        if ac is None:
            return
        from types import SimpleNamespace

        # duck-typed notice: the bus only reads these fields, and importing the
        # credits tracker here drags in provider deps a gateway may not load
        notice = SimpleNamespace(text=text, level="info", kind="ttl", ttl_ms=20000,
                                 key="memnotify", id=f"memnotify:{time.time():.0f}")
        ac._agent_notice_update(session_id, notice)
        _log_line(f"notice {session_id} {text!r}")
    except Exception as exc:
        _log_line(f"notice skip {session_id}: {exc}")


def _on_pre_tool_call(tool_name: str = "", args: dict | None = None, tool_call_id: str = "", **_kw):
    try:
        if (tool_name or "") in {"write_file", "patch"} and tool_call_id:
            path = _in_store(str((args or {}).get("path") or ""))
            if path is not None:
                _pending[tool_call_id] = (str(path), path.exists())
                if len(_pending) > 200:
                    _pending.clear()
    except Exception:
        pass
    return None


def _on_post_tool_call(tool_name: str = "", args: dict | None = None, result=None,
                       session_id: str = "", turn_id: str = "", tool_call_id: str = "", **_kw):
    try:
        existed = None
        if tool_call_id and tool_call_id in _pending:
            _path, existed = _pending.pop(tool_call_id)
        line = _line_for(tool_name, args or {}, existed)
        if line is None or not session_id:
            return None
        key = (session_id, str(turn_id or ""), line)
        if key in _seen:
            return None
        _seen.add(key)
        if len(_seen) > 500:
            _seen.clear()
        target = _target(session_id)
        if target is None:
            _tui_notice(session_id, line)
            return None
        _send(target[0], line, target[1])
    except Exception as exc:  # never break a tool call
        _log_line(f"hook error: {exc}")
    return None


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    _log_line("memnotify registered (chat status lines)")
