# -*- coding: utf-8 -*-
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
# See the NOTICE file for attribution requirements.
"""
Memory-Shaper plugin for Hermes Agent.

Enforces the flat keyword index and (since 1.6.0) the hidden memory-relevance
self-report.

v1.2.0 fix (2026-09-15): the original __init__.py referenced unbound names
(handle_pre_tool_call, _hpc, handle_post_tool_call), so the plugin loaded and
registered zero hooks. It now delegates to plugin.register().

v1.6.0 fix: it used to re-register by hand, which meant a hook added to
plugin.register() could be missing from whichever entry point the host picked.
One registration path, always: plugin.register(). The try/except only exists
because this directory's name contains a hyphen, so it can never be a package
under a normal import — pytest and any path-based loader hit the absolute form.
"""
try:
    from .plugin import register  # noqa: F401
except ImportError:  # imported as a top-level module (path-based loader)
    from plugin import register  # type: ignore  # noqa: F401
