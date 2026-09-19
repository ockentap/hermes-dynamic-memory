# -*- coding: utf-8 -*-
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
# See the NOTICE file for attribution requirements.
"""
Memory-Shaper plugin for Hermes Agent.
Registers pre_tool_call hook and tool_execution middleware.

v1.2.0 fix (2026-09-15): the original __init__.py referenced
unbound names (handle_pre_tool_call, _hpc, handle_post_tool_call)
causing silent NameError → plugin loaded but registered zero hooks.
This file now properly imports from plugin.py.
"""
from .plugin import handle_pre_tool_call


def register(ctx):
    """Register pre_tool_call hook + tool_execution middleware."""
    # pre_tool_call hook (fires for terminal/file/execute_code)
    ctx.register_hook('pre_tool_call', handle_pre_tool_call)

    # tool_execution middleware (fires for memory() in _AGENT_LOOP_TOOLS)
    # Imported lazily to keep the hook module load cheap.
    try:
        from .plugin import handle_tool_execution_middleware
        ctx.register_middleware('tool_execution', handle_tool_execution_middleware)
    except Exception as exc:  # pragma: no cover
        # middleware unavailable; hook still protects non-memory tools
        pass