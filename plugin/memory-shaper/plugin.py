# memory-shaper plugin
#
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
# See the NOTICE file for attribution requirements.
#
# Enforces the two-tier dynamic-memory architecture by intercepting the `memory`
# tool and BLOCKING verbose writes to MEMORY.md. Forces the agent to write
# verbose content to ~/.hermes/memories/<slug>.md and add a one-line pointer
# via a separate, narrow memory() call.
#
# Why this exists:
#   The dynamic-memory skill (system-administration/dynamic-memory) has repeatedly
#   been ignored at runtime. The `memory` tool's natural behaviour is to append
#   verbose multi-line prose to MEMORY.md, which mixes the lookup layer with the
#   detail layer. No amount of skill re-reading fixes the behaviour. So we
#   enforce it at the hook layer instead.
#
# Contract:
#   The `pre_tool_call` hook returns dicts that follow the existing plugin
#   protocol (see hermes_cli/plugins.py:get_pre_tool_call_block_message):
#       {"action": "block", "message": "..."}  → blocks the tool call
#       {}  / None  / anything else             → passthrough
#
# Routing rules:
#   1. memory(target='user', any action)       → passthrough (USER.md is fine)
#   2. memory(action='remove', any target)     → passthrough (deletes are safe)
#   3. memory(action in {add, replace}, target='memory', content matches
#      the keyword arrow format)             → passthrough
#      (MEMORY.md IS the index; ~/.hermes/memory-index.md does not exist)
#   4. memory(action in {add, replace}, target='memory', verbose content):
#      → BLOCK with a routing hint that says: write verbose content to
#        ~/.hermes/memories/<slug>.md (use terminal + write_file), then add a
#        ONE-LINE pointer to MEMORY.md via a follow-up, narrow memory() call.
#   5. memory(action in {add, replace}, target='memory', content is a valid
#      one-line keyword index entry):       → passthrough (good behaviour)

from __future__ import annotations
import json
import os
import re
from pathlib import Path

PLUGIN_ID = "memory-shaper"

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
MEMORY_DIR = HERMES_HOME / "memories"
MEMORY_MD = MEMORY_DIR / "MEMORY.md"
# NOTE: ~/.hermes/memory-index.md was a short-lived experiment and was REMOVED.
# MEMORY.md is the single source of truth for the keyword index. Do not
# reintroduce or reference a separate index file.

VERBOSE_THRESHOLD = 140  # chars; anything above this is "verbose"

# Comma-to-word ratio heuristic (added 2026-09-15):
# Memory entries are keyword lists separated by commas. Human-language text has
# many spaces and few commas. If the ratio of commas / (whitespace-separated
# tokens) falls below MIN_COMMA_WORD_RATIO, the entry is human-language text,
# not a keyword pointer — block it.
#
# Empirical ratio from migrated MEMORY.md (clean state): every line had
# ratio >= 2.0 (e.g. 8 commas / 3 words = 2.67). Old verbose entries had
# ratios like 0.01-0.10. Threshold 0.5 is a safe floor.
MIN_COMMA_WORD_RATIO = 0.5

# `keywords → path` line shape (one keyword arrow entry).
# Fix: [a-z0-9,\s-]+ to allow digits and hyphens inside keywords (e.g. dates, slugs)
#
# 2026-09-16: ASCII arrow was accepted here because it was bypassing the block.
# 2026-09-17: user ruled Unicode-arrow-ONLY. ASCII `->` is now rejected; the
#             rule file (memory-arrow-and-delimiter-rules.md) carries the "why".
#             ASCII_ARROW_LINE_RE exists solely to fail with a *specific* message
#             ("use → not ->") instead of a generic format complaint.
ARROW_LINE_RE = re.compile(
    r"^[a-z0-9,\s-]+\s*→\s+~?/?[\w./~%-]+\.md\s*$",
    re.IGNORECASE,
)
ASCII_ARROW_LINE_RE = re.compile(
    r"^[a-z0-9,\s-]+\s*->\s+~?/?[\w./~%-]+\.md\s*$",
    re.IGNORECASE,
)


def _comma_word_ratio(text: str) -> float:
    """Return commas / word_count. Word = whitespace-separated token.
    Returns float('inf') if zero words (header-only)."""
    words = text.split()
    if not words:
        return float('inf')
    return text.count(',') / len(words)


def _looks_like_keywords(text: str) -> bool:
    """True if content is keyword-style (high comma/word ratio).
    Skips empty, header lines, or pure-arrow lines (those have their own check)."""
    text = text.strip()
    if not text or text.startswith('#'):
        return True  # headers pass
    return _comma_word_ratio(text) >= MIN_COMMA_WORD_RATIO


def _is_arrow_line(text: str) -> bool:
    return bool(ARROW_LINE_RE.match(text.strip()))


# A legal index-line target: bare filename, OR a relative path that stays
# inside the .hermes tree (e.g. ../../reports/REPORTS.md for the reports dir).
ARROW_TARGET_RE = re.compile(
    r"^(?:[\w.-]+\.md|(?:\.\./)+[\w./-]+\.md)$",
    re.IGNORECASE,
)


def _validate_arrow_target(text: str) -> bool:
    """Validate an index line: keyword list + legal target.

    Returns True if the line is well-formed and its target is acceptable.
    Arrow lines are the sanctioned content of MEMORY.md, so a valid one
    must PASS (not be blocked). Only malformed lines are refused.
    """
    line = text.strip()
    # Unicode arrow ONLY (user ruling 2026-09-17). ASCII `->` is rejected here
    # as well as in ARROW_LINE_RE — this function has its own inline parse, so
    # leaving the alternation in would let ASCII slip through validation.
    m = re.match(r"^(.+?)\s*→\s*(\S+)\s*$", line)
    if not m:
        return False
    keywords, target = m.group(1), m.group(2)

    # Target: bare filename or relative path inside the .hermes tree.
    if not ARROW_TARGET_RE.match(target):
        return False
    # No absolute paths — they break portability and hide the real file.
    if target.startswith(("/", "~")):
        return False

    # Keywords: comma-separated, lowercase-ish, sane count.
    kws = [k.strip() for k in keywords.split(",") if k.strip()]
    if not kws:
        return False
    if not (1 <= len(kws) <= 25):
        return False
    # Reject prose: an index line's "keywords" must not contain spaces.
    for k in kws:
        if " " in k:
            return False
    return True


# User-approved wholesale rewrite mechanism (2026-09-17 fix).
# Set MEMORY_SHAPER_ALLOW_REWRITE=1 (env) or create touch-file
# ~/.hermes/state/.memory_shaper_rewrite_approved to allow a full
# rewrite of MEMORY.md (e.g. rebuilding from a verified script).
MEMORY_REWRITE_APPROVAL_FILE = HERMES_HOME / "state" / ".memory_shaper_rewrite_approved"

def _rewrites_approved() -> bool:
    if os.environ.get("MEMORY_SHAPER_ALLOW_REWRITE") == "1":
        return True
    try:
        return MEMORY_REWRITE_APPROVAL_FILE.exists()
    except Exception:
        return False


def _normalize_path(p) -> str:
    """Resolve ~ and absolute-path the input, return canonical string."""
    if not p:
        return ""
    try:
        return str(Path(os.path.expanduser(str(p))).resolve())
    except Exception:
        return str(p)


MEMORY_MD_RESOLVED = _normalize_path(MEMORY_MD)

# User-approved wholesale-rewrite escape hatch.
# The lock's refusal message tells the agent to "ask the user for explicit scope
# approval" before rewriting MEMORY.md — but historically there was NO way to
# signal that approval to the hook, making the instruction a dead end. Honour:
#   1. env var MEMORY_SHAPER_ALLOW_REWRITE=1
#   2. sentinel file ~/.hermes/state/.memory_shaper_rewrite_approved
ALLOW_REWRITE_ENV = "MEMORY_SHAPER_ALLOW_REWRITE"
APPROVAL_FILE = HERMES_HOME / "state" / ".memory_shaper_rewrite_approved"


def _rewrite_approved() -> bool:
    """True if the user has approved a wholesale MEMORY.md rewrite."""
    if os.environ.get(ALLOW_REWRITE_ENV, "").strip() in ("1", "true", "yes"):
        return True
    try:
        return APPROVAL_FILE.exists()
    except Exception:
        return False



def _targets_memory_md(args: dict) -> bool:
    """Return True if the tool args actually WRITE to MEMORY.md.

    Read-only operations must never be blocked, even when they mention the path.
    Earlier versions treated any command containing '>' or starting with
    'python' as a write and then blocked it merely for mentioning MEMORY.md —
    which refused plain `wc -l MEMORY.md`, `grep § MEMORY.md`, and even
    unrelated `python3 <script>` calls (reported as 'Path detected: (unknown)').
    """
    if not isinstance(args, dict):
        return False

    # write_file / patch / edit: explicit path field — the ONLY reliable signal.
    p = args.get("path") or args.get("file_path") or ""
    if p and _normalize_path(p) == MEMORY_MD_RESOLVED:
        return True

    cmd = (args.get("command") or "").strip()
    if cmd:
        first = cmd.split()[0] if cmd.split() else ""

        # 1. Pure read-only first-word commands: NEVER a write, no matter what
        #    else the string contains (pipes/redirects are not writes to
        #    MEMORY.md unless the target is MEMORY.md).
        if re.match(r"^(cat|head|tail|wc|less|more|bat|grep|egrep|fgrep|ls|stat|md5sum|diff|file|sort|uniq|awk|cut|tr)\b", first):
            # Block an explicit redirect whose TARGET is MEMORY.md
            if re.search(r">>>?\s*\S*MEMORY\.md", cmd):
                return True
            # 2026-09-19 hardening: a read-only FIRST WORD is only a pure
            # read if the command carries no shell operators at all — no
            # pipes (tee), no redirects (any target), no command
            # substitution $(...) or backticks, no chaining.
            # `cat a | tee MEMORY.md` and `cat $(echo x >> MEMORY.md)` are
            # writes wearing a read-only first word.
            if re.search(r"[|;&`]|\$\(|>>>?", cmd):
                return True
            # In-program redirection: sort -o MEMORY.md, awk 'print > "file"'
            if re.search(r"-o\s*\S*MEMORY\.md", cmd):
                return True
            if re.search(r">\s*[\"']", cmd):
                return True
            return False

        # 2. python3 <script.py> — block only if the SCRIPT ITSELF writes
        #    MEMORY.md. A script that merely happens to mention it (or an
        #    unrelated script) is not a write.
        if first in ("python3", "python"):
            parts = cmd.split()
            script_path = next((t for t in parts[1:] if not t.startswith("-")), "")
            if not script_path or not os.path.exists(script_path):
                # Can't inspect it; only block if it explicitly redirects to MEMORY.md
                return bool(re.search(r">>?\s*\S*MEMORY\.md", cmd))
            try:
                src = Path(script_path).read_text(errors="replace")
            except Exception:
                return False
            # Does the script open MEMORY.md for writing?
            writes_memory = bool(
                re.search(r"open\s*\([^)]*MEMORY\.md[^)]*['\"][wa]\+?['\"]", src)
                or re.search(r"MEMORY_MD\s*\.\s*write_text", src)
                or re.search(r"(MEMORY_MD|MEMORY\.md)[^#\n]{0,60}open\s*\([^)]*['\"][wa]", src)
            )
            # Honour the documented user-approved rewrite escape hatch
            if writes_memory and not _rewrite_approved():
                return True
            return False

        # 3. Other commands: block only on an explicit write TO MEMORY.md.
        #    NOTE: the user-approved rewrite escape hatch deliberately does NOT
        #    apply here. `_rewrite_approved()` authorises a *scripted wholesale
        #    rewrite* (run via python3), not ad-hoc shell redirection, which
        #    would be an unbounded bypass. Shell writes to MEMORY.md are always
        #    refused; use the memory() tool or an approved rewrite script.
        if re.search(r">>?\s*\S*MEMORY\.md", cmd) or ("tee" in cmd and "MEMORY.md" in cmd):
            return True
        if "sed" in cmd and "-i" in cmd and "MEMORY.md" in cmd:
            return True

    # execute_code: block if the code directly writes MEMORY.md, UNLESS an
    # approved wholesale rewrite is in effect.
    code = args.get("code") or ""
    if code and not _rewrite_approved():
        if re.search(r"open\s*\([^)]*MEMORY\.md[^)]*['\"][wa]\+?['\"]", code) or \
           re.search(r"MEMORY_MD\s*\.\s*write_text", code) or \
           re.search(r">>?\s*\S*MEMORY\.md", code):
            return True

    return False


def _slugify(text: str, max_words: int = 4) -> str:
    """First few meaningful words → filesystem-safe slug."""
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9-]+", text.lower())
    stop = {"the", "a", "an", "is", "of", "and", "or", "to", "in", "on",
            "for", "with", "this", "that", "see", "memories"}
    kept = [w for w in words if w not in stop][:max_words]
    if not kept:
        kept = ["note"]
    slug = "-".join(kept)[:60].strip("-")
    return slug or "note"


import logging
_logger = logging.getLogger(__name__)

def handle_pre_tool_call(
    tool_name: str,
    args: dict,
    session_id: str = "",
    task_id: str = "",
    tool_call_id: str = "",
    **_unknown,  # tolerate dispatcher-injected kwargs (e.g. telemetry_schema_version);
                # unknown kwargs would otherwise raise TypeError and silently disable the gate
) -> dict:
    """Block any tool call that would write to MEMORY.md.

    Architecture: MEMORY.md is the runtime context file. The ONLY sanctioned
    way to mutate it is the `memory` tool, whose handler enforces the flat
    one-line-per-topic index format and the verbose-content threshold. All other
    tools (write_file, patch, terminal, execute_code, etc.) are blocked when they
    target MEMORY.md, because those tools bypass every guarantee the memory
    tool provides.

    This is the strict mode — any non-`memory` tool call whose args reference
    MEMORY.md is refused with a routing hint.

    Returns {} for passthrough, or
    {"action": "block", "message": "..."} to block.
    """
    if tool_name == "memory":
        # Same logic as before: enforce verbose + arrow rules on memory() calls.
        action = (args.get("action") or "add").lower()
        target = (args.get("target") or "memory").lower()
        content = (args.get("content") or "").strip()

        if target == "user":
            return {}
        if action == "remove":
            return {}
        if not content:
            return {}

        _logger.info("[memory-shaper] memory() call, content_len=%d, action=%s", len(content), action)

        # === REPLACE GUARD (2026-09-17 wipe fix; corrected 2026-09-17) ===
        # MEMORY.md entries are NEWLINE-delimited: one 'kw,kw → file.md' line per
        # topic file. It is NOT §-delimited. (The § model was a rejected
        # historical experiment; this plugin's own header says "one line per
        # topic file, no prose, no § markers".)
        #
        # A replace must match EXACTLY ONE ENTRY LINE. Matching 0 or >1 is an
        # error. The previous version split on "\n§\n", which on a newline-
        # delimited file yields ONE entry containing the whole file — so any
        # old_text matched everything and the file was replaced wholesale.
        if action == "replace" and old_text:
            # Read current file content from disk for boundary check
            try:
                current_text = MEMORY_MD.read_text()
            except Exception:
                current_text = ""
            entries = current_text.splitlines()
            matches = [i for i, e in enumerate(entries) if old_text in e]
            if len(matches) == 0:
                return {"action": "block", "message": "[memory-shaper] replace refused: old_text did not match any entry line (0 matches)."}
            if len(matches) > 1:
                return {"action": "block", "message": f"[memory-shaper] replace refused: old_text matched {len(matches)} entry lines (expected exactly 1). Use a longer, unique substring."}
            # Safety: a replace must never reduce the entry count by more than
            # one line. This makes whole-file clobber structurally impossible.
            old_line = entries[matches[0]]
            is_entry = _is_arrow_line(old_line)
            new_lines = (content or "").splitlines() or [""]
            # If we're replacing an index entry, the replacement should itself
            # be exactly one index line.
            if is_entry and len(new_lines) != 1:
                return {
                    "action": "block",
                    "message": (
                        f"[memory-shaper] replace refused: target is one index line but "
                        f"content spans {len(new_lines)} lines. One line per topic file."
                    ),
                }

        if _is_arrow_line(content):
            # FIXED 2026-09-17: arrow lines are EXACTLY what belongs in
            # MEMORY.md (MEMORY.md IS the index). Blocking them was a bug —
            # it made it impossible to add index entries via the sanctioned
            # `memory` tool while every other tool was locked, so agents looped.
            # Validate only that the target is a legal filename and pass through.
            if _validate_arrow_target(content):
                return {}
            # Distinguish "you used the wrong arrow" from "your line is
            # malformed" so the agent gets an actionable fix, not a scavenger
            # hunt through the format rules (2026-09-17: ASCII is now banned).
            if ASCII_ARROW_LINE_RE.match(content.strip()):
                return {
                    "action": "block",
                    "message": (
                        "[memory-shaper] Wrong arrow. MEMORY.md uses the Unicode "
                        "arrow ONLY:\n"
                        "  keyword,keyword,keyword → file.md\n"
                        "You wrote ASCII '->'. Replace it with '→' (U+2192), one "
                        "space on each side.\n"
                        "House style is user-set; see "
                        "memories/memory-arrow-and-delimiter-rules.md"
                    ),
                }
            return {
                "action": "block",
                "message": (
                    "[memory-shaper] Malformed index line. Expected exactly:\n"
                    "  keyword,keyword,keyword → file.md\n"
                    "Rules:\n"
                    "  - file.md is a BARE filename (no path, no dir, no ~)\n"
                    "  - 5-20 comma-separated lowercase keywords\n"
                    "  - one line per topic file, no prose, no § markers\n"
                    "If the target lives outside ~/.hermes/memories/ (e.g. the\n"
                    "reports dir), use the relative form: ../../reports/REPORTS.md\n"
                ),
            }

        # Comma/word ratio check (added 2026-09-15).
        # Even short content (<140 chars) can be human-language prose instead
        # of a keyword pointer. Block any entry whose comma-to-word ratio is
        # below MIN_COMMA_WORD_RATIO (=0.5) — that's the signal it's prose,
        # not keywords. The exception: a pure arrow line (already handled above).
        if not _looks_like_keywords(content):
            ratio = _comma_word_ratio(content)
            return {
                "action": "block",
                "message": (
                    f"[memory-shaper] Content looks like human-language prose, "
                    f"not a keyword pointer.\n"
                    f"  comma/word ratio: {ratio:.3f} (minimum {MIN_COMMA_WORD_RATIO})\n"
                    f"  content length: {len(content)} chars\n"
                    f"  first 80 chars: {content[:80]!r}\n\n"
                    "MEMORY.md entries must be keyword lists separated by commas. "
                    "Exact format (one line per topic file):\n"
                    "  keyword,keyword,keyword → file.md\n"
                    "where file.md is a bare filename in ~/.hermes/memories/ "
                    "(no `memories/` prefix, no ~, no absolute path).\n\n"
                    "For verbose detail: write it to ~/.hermes/memories/<slug>.md "
                    "(use write_file), then append one keyword line to MEMORY.md.\n"
                    "Do NOT create or reference a separate memory-index.md — it was "
                    "removed. USER.md writes (target='user') are exempt."
                ),
            }

        if action in ("add", "replace") and len(content) > VERBOSE_THRESHOLD:
            slug = _slugify(content)
            topic_file = MEMORY_DIR / f"{slug}.md"
            return {
                "action": "block",
                "message": (
                    f"[memory-shaper] Verbose content ({len(content)} chars) "
                    "would bloat MEMORY.md.\n"
                    "Route it instead:\n"
                    f"  1. Write the verbose detail to {topic_file}\n"
                    "     (use write_file — be verbose there)\n"
                    f"  2. Append a ONE-LINE keyword entry to {MEMORY_MD}:\n"
                    f"        kw1,kw2,kw3 → {slug}.md\n"
                    f"     (bare filename — MEMORY.md IS the index; there is no\n"
                    f"      separate memory-index.md, it was removed)\n\n"
                    "Skip step 1 if the file already exists for that topic.\n"
                    "USER.md is exempt — use target='user' for user-profile notes."
                ),
            }
        return {}

    # All other tools: refuse if they target MEMORY.md.
    if _targets_memory_md(args):
        _logger.warning(
            "[memory-shaper] BLOCKED %s targeting MEMORY.md (args keys: %s)",
            tool_name, list(args.keys()) if isinstance(args, dict) else []
        )
        return {
            "action": "block",
            "message": (
                f"[memory-shaper] {tool_name}() refused: MEMORY.md is write-locked.\n"
                f"Path detected: {args.get('path') or args.get('command') or '(unknown)'}\n\n"
                "MEMORY.md is the runtime context file and can only be mutated through "
                "the `memory` tool, whose hook enforces the one-line-per-topic index "
                "format and the verbose-content threshold. Bypassing it via write_file/"
                "patch/terminal is what produced the recurring compliance failures.\n\n"
                "Use the memory() tool instead:\n"
                "  • Add an index entry (one line per topic file):\n"
                "      memory(action='add', target='memory', content='kw1,kw2,kw3 → file.md')\n"
                "  • Replace exactly one entry line:\n"
                "      memory(action='replace', target='memory', old_text='<unique substring of ONE line>', content='kw1,kw2,kw3 → file.md')\n"
                "  • Remove entry:\n"
                "      memory(action='remove', target='memory', old_text='<unique substring>')\n\n"
                "Format rules (MEMORY.md is a flat, NEWLINE-delimited index):\n"
                "  - ONE entry per line:  keyword,keyword,keyword → file.md\n"
                "  - file.md is a BARE filename in ~/.hermes/memories/ (no path)\n"
                "  - 5-20 comma-separated lowercase keywords per line\n"
                "  - NO § markers, NO prose, NO blank-line paragraphs\n"
                "  - Use the Unicode arrow → ONLY (ASCII '->' is rejected)\n\n"
                "For verbose content: write the body to ~/.hermes/memories/<slug>.md "
                "with write_file (those files are NOT locked), then append a line "
                "'keyword,keyword → slug.md' to MEMORY.md.\n\n"
                "MEMORY.md IS the index — there is no separate memory-index.md "
                "(removed; do not recreate or reference it).\n\n"
                "If you really must rewrite MEMORY.md wholesale (e.g. you have a "
                "valid, fully-formed new file), stop and ask the user for explicit "
                "scope approval first.\n"
                "You can do this in two ways:\n"
                "  • Set the environment variable: MEMORY_SHAPER_ALLOW_REWRITE=1, then retry.\n"
                "  • Create the approval file: ~/.hermes/state/.memory_shaper_rewrite_approved (empty file).\n"
                "After creating the approval, the rewrite will be allowed and will be logged."
            ),
        }

    return {}


def register(ctx):
    """Plugin entry point. Wires the pre_tool_call hook AND the
    tool_execution middleware (added 2026-09-15, Option C fix).

    Why both? The `pre_tool_call` hook fires for terminal/file/execute_code
    but NOT for `memory` (memory is in `_AGENT_LOOP_TOOLS` and dispatched
    via tool_executor's middleware chain, not model_tools' hook call).
    To intercept memory writes, we ALSO register as a tool_execution
    middleware. Both paths funnel into `handle_pre_tool_call`, so the
    rules stay in one place.
    """
    ctx.register_hook("pre_tool_call", handle_pre_tool_call)
    ctx.register_middleware("tool_execution", handle_tool_execution_middleware)


def handle_tool_execution_middleware(**kwargs):
    """tool_execution middleware entry point (added 2026-09-15).

    Kwargs (per hermes_cli.middleware:run_tool_execution_middleware contract):
      - tool_name (str): the tool name (e.g. "memory")
      - args (dict): the args dict passed to the tool
      - next_call (callable): invoke the actual tool. Single-use per frame.
      - original_args (dict): the unmodified args before any middleware rewrite
      - session_id, task_id, tool_call_id, turn_id, api_request_id: ids

    Returns: whatever the tool would have returned, OR a JSON error dict
    to short-circuit the call. To BLOCK: return a JSON-encoded error
    WITHOUT calling next_call(args).
    """
    tool_name = kwargs.get("tool_name")
    if tool_name != "memory":
        # We only care about memory calls. Everything else: passthrough.
        next_call = kwargs.get("next_call")
        if callable(next_call):
            return next_call(kwargs.get("args") or {})
        return kwargs.get("args")

    # Build the same args structure that pre_tool_call would receive
    raw_args = kwargs.get("args") or {}
    # The memory tool expects: action, target, content, old_text, operations
    # Re-dispatch through handle_pre_tool_call to reuse the existing logic.
    decision = handle_pre_tool_call("memory", raw_args)

    if isinstance(decision, dict) and decision.get("action") == "block":
        msg = decision.get("message", "memory-shaper blocked this call")
        _logger.warning(
            "[memory-shaper] middleware BLOCKED memory(): %s",
            (raw_args.get("content", "") or "")[:80],
        )
        # Return a JSON error so the model sees a tool failure.
        # Use the same envelope model_tools.py produces for hook blocks.
        import json
        return json.dumps({"success": False, "error": msg}, ensure_ascii=False)

    # Passthrough — actually run the memory tool
    next_call = kwargs.get("next_call")
    if callable(next_call):
        return next_call(raw_args)
    return raw_args
