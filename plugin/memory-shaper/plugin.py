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

def _hermes_home() -> Path:
    """Resolve the active profile's home on EVERY call.

    A process can serve several profiles; os.environ read at import time is
    frozen to the launch profile and silently leaks the wrong memories dir
    (teknium1 review 2026-10-29). hermes_constants.get_hermes_home() is the
    profile-aware resolver in Hermes >= 0.22; fall back to env/home otherwise.
    """
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def _memory_dir() -> Path:
    return _hermes_home() / "memories"


def _memory_md() -> Path:
    return _memory_dir() / "MEMORY.md"


# Module-level fallbacks exist only for import-time message strings; all
# decision paths resolve through the functions above.
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


# Hermes' built-in memory store (tools/memory_tool_store.py) joins entries with
# ENTRY_DELIMITER = "\n§\n". The dynamic-memory format is NEWLINE-delimited: a
# newline means a new entry, so no separator token is required or wanted. These
# lines are therefore runtime artifacts rather than content. We cannot stop the
# store emitting them, so we recognise and ignore them everywhere we reason
# about entry boundaries (replace-guard, entry counts).
SEPARATOR_CHARS = {"\u00a7", "\u2550", "="}


def _is_separator_line(text: str) -> bool:
    """True for a bare separator/ruler line emitted by the memory store.

    Covers the single "§" between entries and the "═"*46 ruler the tool renders
    in its human-readable output, but not an index line that merely contains a
    § character somewhere in its content.
    """
    s = (text or "").strip()
    if not s:
        return False
    if s in SEPARATOR_CHARS:
        return True
    return len(s) >= 3 and set(s) <= SEPARATOR_CHARS


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
def _approval_file() -> Path:
    return _hermes_home() / "state" / ".memory_shaper_rewrite_approved"

def _rewrites_approved() -> bool:
    if os.environ.get("MEMORY_SHAPER_ALLOW_REWRITE") == "1":
        return True
    try:
        return _approval_file().exists()
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


def _memory_md_resolved() -> str:
    return _normalize_path(_memory_md())

# User-approved wholesale-rewrite escape hatch.
# The lock's refusal message tells the agent to "ask the user for explicit scope
# approval" before rewriting MEMORY.md — but historically there was NO way to
# signal that approval to the hook, making the instruction a dead end. Honour:
#   1. env var MEMORY_SHAPER_ALLOW_REWRITE=1
#   2. sentinel file ~/.hermes/state/.memory_shaper_rewrite_approved
ALLOW_REWRITE_ENV = "MEMORY_SHAPER_ALLOW_REWRITE"
def _rewrite_approved() -> bool:
    """True if the user has approved a wholesale MEMORY.md rewrite."""
    if os.environ.get(ALLOW_REWRITE_ENV, "").strip() in ("1", "true", "yes"):
        return True
    try:
        return _approval_file().exists()
    except Exception:
        return False


# ── Template-line protection and one-time placeholder cleanup ────────────────
_TEMPLATE_LINE_MSG = (
    "[memory-shaper] refused: that text is the template line "
    "'keyword,keyword,keyword → file.md'. It is structural — the header block ends "
    "there, and the watchdog, validator and memory tool all locate the first entry "
    "by it. Editing or deleting it needs explicit user approval "
    "(MEMORY_SHAPER_ALLOW_REWRITE=1 or ~/.hermes/state/.memory_shaper_rewrite_approved)."
)

_TEMPLATE_NOTE_PREFIX = "TEMPLATE \u2014"

# The example entries shipped inside MEMORY.template.md. They are placeholders for
# the reader, not memories: once the user writes a real entry they must go, or the
# index carries lines pointing at demo files that do not exist.
_TEMPLATE_EXAMPLES = {
    "python-env.md", "js-toolchain.md", "java-performance.md", "deploy-pipeline.md",
    "laptop-hardware.md", "home-network.md", "git-workflow.md",
}


def _is_template_target(old_text: str) -> bool:
    """True when *old_text* identifies the structural template line."""
    t = (old_text or "").strip().lstrip("`")
    if not t:
        return False
    if t.startswith("keyword,keyword,keyword"):
        return True
    template = "keyword,keyword,keyword \u2192 file.md"
    return len(t) >= 24 and t in template


def _autoclean_template_lines() -> None:
    """Drop the template's own placeholder lines after the first real entry.

    Removes (a) the 'TEMPLATE — …' note and (b) example entries whose target file
    does not exist in the memories directory. Idempotent; no-op once clean. Never
    touches the structural template line, the header prose, or a real entry.
    """
    path = _memory_md()
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return
    memdir = path.parent
    keep, changed = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(_TEMPLATE_NOTE_PREFIX):
            changed = True
            continue
        m = re.search(r"\u2192\s*([A-Za-z0-9_.\-]+\.md)\s*$", s)
        if m and m.group(1) in _TEMPLATE_EXAMPLES and not (memdir / m.group(1)).exists():
            changed = True
            continue
        keep.append(line)
    if not changed:
        return
    try:
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".mem_clean_")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(keep) + "\n")
        os.replace(tmp, path)
        _logger.info("[memory-shaper] removed %d template placeholder line(s)",
                     len(text.splitlines()) - len(keep))
    except Exception:
        pass



def _targets_memory_md(args: dict, tool_name: str = "") -> bool:
    """Return True if the tool args actually WRITE to MEMORY.md.

    Read-only operations must never be blocked, even when they mention the path.
    Earlier versions treated any command containing '>' or starting with
    'python' as a write and then blocked it merely for mentioning MEMORY.md —
    which refused plain `wc -l MEMORY.md`, `grep § MEMORY.md`, and even
    unrelated `python3 <script>` calls (reported as 'Path detected: (unknown)').

    `tool_name` disambiguates tools that carry a `path` argument but do not
    write it. `read_file` takes the same `path` field as `write_file`, so a
    path-only check blocked the agent from reading the very index it is
    responsible for maintaining (the audit-lockout class). Only tools that
    actually mutate the path may be refused on a path match.
    """
    if not isinstance(args, dict):
        return False

    # Tools whose `path` argument is a WRITE target. read_file is deliberately
    # absent: reading MEMORY.md is always allowed.
    _PATH_WRITING_TOOLS = {"write_file", "patch", "edit", "create_file"}
    if tool_name and tool_name not in _PATH_WRITING_TOOLS:
        # Not a path-writing tool: the `path` field cannot be a write vector.
        pass_writes = False
    else:
        pass_writes = True

    # write_file / patch / edit: explicit path field — the ONLY reliable signal.
    p = args.get("path") or args.get("file_path") or ""
    if pass_writes and p and _normalize_path(p) == _memory_md_resolved():
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

def _check_patch_guard(old: str, content: str) -> dict | None:
    """v0.22+ `patch`: content replaces the old_text SPAN inside one entry line;
    the rest of the line is kept. Validate the RESULTING line, not the fragment —
    checking the fragment alone is a whole-entry (replace) model, and it blocks
    legitimate keyword-additions like old="heap" new="heap,gc,profiler".

    Returns a block dict when the patch would produce a malformed index line.
    Ambiguity mirrors the tool: old_text must select exactly one entry and occur
    once inside it; otherwise the store refuses the write itself, so we pass and
    let it (the file cannot change).
    """
    if not old:
        return None  # schema-required old_text; missing -> the tool itself refuses
    if _is_template_target(old) and not _rewrite_approved():
        return {"action": "block", "message": _TEMPLATE_LINE_MSG}
    try:
        entries = _memory_md().read_text().splitlines()
    except Exception:
        return None  # unreadable file: the write cannot corrupt what we cannot read
    hits = [i for i, e in enumerate(entries) if old in e]
    if len(hits) != 1:
        return None  # 0 or ambiguous: the store rejects; the file stays untouched
    line = entries[hits[0]]
    if _is_separator_line(line) or not _is_arrow_line(line):
        return None  # header/prose/separator: not an index entry we can corrupt
    # Store semantics (memory_tool_store._span_occurrences): occurrences
    # OVERLAPPING count too ('aa' twice in 'aaa') and the write is rejected
    # then, not applied. Mirror that exactly.
    occ = sum(line.startswith(old, i) for i in range(len(line) - len(old) + 1))
    if occ != 1:
        return None  # 0 or ambiguous span: the store rejects; file untouched
    # A patch must not introduce line breaks: the store keeps entries one per
    # line, and a smuggled \n turns one entry into a corrupt multi-line blob.
    if "\n" in (content or "") or "\r" in (content or ""):
        return {
            "action": "block",
            "message": (
                "[memory-shaper] patch refused: content contains a line break. "
                "MEMORY.md entries are one line each; a patch that inserts \\n "
                "splits an entry and corrupts the index."
            ),
        }
    resulting = line.replace(old, content)
    if "\n" in resulting or "\r" in resulting:
        return {
            "action": "block",
            "message": (
                "[memory-shaper] patch refused: the resulting entry would span "
                "multiple lines. MEMORY.md entries are one line each."
            ),
        }
    # Full index-line validation, not just the loose regex: the replacement may
    # smuggle an invalid target (..md.txt, absolute path, prose keywords).
    if _is_arrow_line(resulting) and _validate_arrow_target(resulting) \
            and not ASCII_ARROW_LINE_RE.match(resulting.strip()):
        return None
    kw = (content[:40] + "\u2026") if len(content) > 40 else content
    return {
        "action": "block",
        "message": (
            "[memory-shaper] patch refused: the resulting index line would be malformed.\n"
            f"  before: {line[:100]}\n"
            f"  after:  {resulting[:100]}\n"
            "Every MEMORY.md line must keep the form:\n"
            "  keyword,keyword,keyword \u2192 file.md\n"
            f"Your patch replaces {kw!r}; choose a replacement that keeps the "
            "keywords comma-separated and the Unicode arrow + bare .md target intact."
        ),
    }


def _check_replace_guard(old: str, content: str, memory_md_path: str | None = None) -> dict | None:
    """Validate a replace/patch guard: match against entries, count check, separator rejection."""
    target = Path(memory_md_path) if memory_md_path else _memory_md()
    try:
        current_text = target.read_text()
    except Exception:
        current_text = ""
    entries = current_text.splitlines()
    matches = [i for i, e in enumerate(entries) if old in e]
    if len(matches) == 0:
        return {"action": "block", "message": "[memory-shaper] replace refused: old_text did not match any entry line (0 matches)."}
    if len(matches) > 1:
        return {"action": "block", "message": f"[memory-shaper] replace refused: old_text matched {len(matches)} entry lines (expected exactly 1). Use a longer, unique substring."}
    old_line = entries[matches[0]]
    if _is_separator_line(old_line):
        return {
            "action": "block",
            "message": (
                "[memory-shaper] replace refused: old_text matched a separator "
                "line emitted by the memory store, not an index entry. "
                "Target the 'keyword,keyword \u2192 file.md' line itself."
            ),
        }
    is_entry = _is_arrow_line(old_line)
    new_lines = (content or "").splitlines() or [""]
    if is_entry and len(new_lines) != 1:
        return {
            "action": "block",
            "message": (
                f"[memory-shaper] replace refused: target is one index line but "
                f"content spans {len(new_lines)} lines. One line per topic file."
            ),
        }
    return None


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

    Strict mode: every non-`memory` tool call whose args hit a RECOGNISED
    write vector for MEMORY.md is refused with a routing hint. The shell
    detection is best-effort against known vectors (redirects, tee, sed -i,
    in-program -o, script/execute_code writes); arbitrary indirection
    (cp/mv/heredoc-via-pipe) is out of scope and disclosed as such.

    Returns {} for passthrough, or
    {"action": "block", "message": "..."} to block.
    """
    if tool_name == "memory":
        # Same logic as before: enforce verbose + arrow rules on memory() calls.
        action = (args.get("action") or "add").lower()
        target = (args.get("target") or "memory").lower()
        # The real tool resolves content with "content wins if non-empty,
        # else new_text fills it" (tools/memory_tool.py #90468). Validate the
        # SAME value that will actually be written.
        content = (args.get("content") or args.get("new_text") or "").strip()
        # old_text is required by replace and unused by the other actions. It was
        # previously referenced without ever being assigned, so every replace
        # raised NameError instead of being validated (caught by the separator
        # regression test, 2026-09-19).
        old_text = (args.get("old_text") or "").strip()

        if target == "user":
            return {}
        if action == "remove":
            if _is_template_target(old_text) and not _rewrite_approved():
                return {"action": "block", "message": _TEMPLATE_LINE_MSG}
            return {}

        # === OPERATIONS[] support (for released Hermes — 2026-10-29 fix per teknium1 review) ===
        # Released Hermes uses batch operations[{"action":"add|patch|remove", ...}] rather
        # than top-level single-op fields. Validate each entry individually; early-return
        # at :382-383 used to skip this entirely.
        operations = args.get("operations") or []
        if isinstance(operations, list) and len(operations) > 0:
            # Re-run all checks on each operation element.
            for idx, op in enumerate(operations):
                if not isinstance(op, dict):
                    continue
                _act = (op.get("action") or "add").lower()
                _tgt = (op.get("target") or "memory").lower()
                # v0.22.5+: "new_text" is an ALIAS; the real tool lets "content"
                # win when both are set (schema: "If both are set, 'content' wins").
                # Reading new_text first here would validate a field that never writes.
                _cont = ((op.get("content") or op.get("new_text")) or "").strip()
                _old = (op.get("old_text") or "").strip()
                if _tgt == "user":
                    continue
                if _act == "remove":
                    if _is_template_target(_old) and not _rewrite_approved():
                        return {"action": "block", "message":
                                f"[memory-shaper] Operation {idx}: " + _TEMPLATE_LINE_MSG}
                    continue
                # v0.22+ patch = SPAN replacement (rest of the entry is kept);
                # validate the resulting line, not the fragment (teknium1 review
                # follow-up: treating patch as whole-entry replace overblocked
                # legitimate keyword additions — proven by the tool oracle gate).
                if _act == "patch":
                    result = _check_patch_guard(old=_old, content=_cont)
                    if result:
                        return {**result, "message":
                                f"[memory-shaper] Operation {idx}: " + result["message"]}
                    continue
                if not _cont:
                    # Empty-content operation → let it pass (removes are already excluded above).
                    continue
                if _is_arrow_line(_cont):
                    if not _validate_arrow_target(_cont):
                        return {
                            "action": "block",
                            "message": (
                                f"[memory-shaper] Operation {idx}: Malformed index line in operations[]. "
                                f"Expected one line: keyword,kw → file.md\n"
                                f"Rules:\n"
                                f"  - file.md is a BARE filename in ~/.hermes/memories/\n"
                                f"  - 5-20 comma-separated lowercase keywords\n"
                                f"  - one line per topic file, no prose, no \u00a7 markers\n"
                                f"  - Unicode arrow \u2192 ONLY (ASCII -> rejected)"
                            ),
                        }
                    continue
                if not _looks_like_keywords(_cont):
                    ratio = _comma_word_ratio(_cont)
                    return {
                        "action": "block",
                        "message": (
                            f"[memory-shaper] Operation {idx}: Content looks like human-language prose, "
                            f"not a keyword pointer.\n"
                            f"  comma/word ratio: {ratio:.3f} (minimum {MIN_COMMA_WORD_RATIO})\n"
                            f"  content length: {len(_cont)} chars\n"
                            f"  first 80 chars: {_cont[:80]!r}\n\n"
                            "MEMORY.md entries must be keyword lists separated by commas. "
                            "Exact format (one line per topic file):\n"
                            "  keyword,keyword,keyword \u2192 file.md\n"
                            "where file.md is a bare filename in ~/.hermes/memories/ "
                            "(no `memories/` prefix, no ~, no absolute path).\n\n"
                            "For verbose detail: write it to ~/.hermes/memories/<slug>.md "
                            "(use write_file), then append one keyword line to MEMORY.md."
                        ),
                    }
                if _act in ("add", "patch") and len(_cont) > VERBOSE_THRESHOLD:
                    slug = _slugify(_cont)
                    topic_file = _memory_dir() / f"{slug}.md"
                    return {
                        "action": "block",
                        "message": (
                            f"[memory-shaper] Operation {idx}: Verbose content ({len(_cont)} chars) "
                            "would bloat MEMORY.md.\n"
                            "Route it instead:\n"
                            f"  1. Write the verbose detail to {topic_file}\n"
                            "     (use write_file — be verbose there)\n"
                            f"  2. Append a ONE-LINE keyword entry to {_memory_md()}:\n"
                            f"        kw1,kw2,kw3 \u2192 {slug}.md\n"
                            f"     (bare filename — MEMORY.md IS the index; there is no\n"
                            f"      separate memory-index.md, it was removed)\n\n"
                            "Skip step 1 if the file already exists for that topic.\n"
                            "USER.md is exempt — use target='user' for user-profile notes."
                        ),
                    }

        # === Top-level single-op path (older Hermes: add/replace with content field) ===
        if not content:
            return {}

        _logger.info("[memory-shaper] memory() call, content_len=%d, action=%s", len(content), action)

        if action == "patch":
            # v0.22+ span semantics: validate the resulting entry line only.
            result = _check_patch_guard(old=old_text, content=content)
            if result:
                return result
            return {}

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
        if action in ("replace", "patch") and old_text:
            # Read current file content from disk for boundary check
            try:
                current_text = _memory_md().read_text()
            except Exception:
                current_text = ""
            entries = current_text.splitlines()
            # The template line is structural: only an approved rewrite may touch it.
            if _is_template_target(old_text) and not _rewrite_approved():
                return {"action": "block", "message": _TEMPLATE_LINE_MSG}
            matches = [i for i, e in enumerate(entries) if old_text in e]
            if len(matches) == 0:
                return {"action": "block", "message": "[memory-shaper] replace refused: old_text did not match any entry line (0 matches)."}
            if len(matches) > 1:
                return {"action": "block", "message": f"[memory-shaper] replace refused: old_text matched {len(matches)} entry lines (expected exactly 1). Use a longer, unique substring."}
            # Safety: a replace must never reduce the entry count by more than
            # one line. This makes whole-file clobber structurally impossible.
            old_line = entries[matches[0]]
            # A separator line is never a valid replace target: replacing it
            # would delete the runtime's own entry boundary instead of content.
            if _is_separator_line(old_line):
                return {
                    "action": "block",
                    "message": (
                        "[memory-shaper] replace refused: old_text matched a separator "
                        "line emitted by the memory store, not an index entry. "
                        "Target the 'keyword,keyword → file.md' line itself."
                    ),
                }
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
            topic_file = _memory_dir() / f"{slug}.md"
            return {
                "action": "block",
                "message": (
                    f"[memory-shaper] Verbose content ({len(content)} chars) "
                    "would bloat MEMORY.md.\n"
                    "Route it instead:\n"
                    f"  1. Write the verbose detail to {topic_file}\n"
                    "     (use write_file — be verbose there)\n"
                    f"  2. Append a ONE-LINE keyword entry to {_memory_md()}:\n"
                    f"        kw1,kw2,kw3 → {slug}.md\n"
                    f"     (bare filename — MEMORY.md IS the index; there is no\n"
                    f"      separate memory-index.md, it was removed)\n\n"
                    "Skip step 1 if the file already exists for that topic.\n"
                    "USER.md is exempt — use target='user' for user-profile notes."
                ),
            }
        # First real entry: drop the template's own placeholder lines. Done HERE as
        # well as after the write, because not every Hermes build routes the memory
        # tool through tool_execution middleware — and the placeholders must go with
        # the first generated memory, not eventually.
        try:
            _ops_all = args.get("operations") or []
            _adds = action == "add" or any(
                (o.get("action") or "add").lower() == "add"
                for o in _ops_all if isinstance(o, dict)
            )
            if _adds:
                _autoclean_template_lines()
        except Exception:
            pass  # cleanup must never break a memory write

        return {}
    if _targets_memory_md(args, tool_name):
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
        result = next_call(raw_args)
        try:
            _act = (raw_args.get("action") or "").lower()
            _ops = raw_args.get("operations") or []
            did_add = _act == "add" or any(
                (o.get("action") or "add").lower() == "add"
                for o in _ops if isinstance(o, dict)
            )
            if did_add and '"success": false' not in str(result):
                _autoclean_template_lines()
        except Exception:
            pass  # placeholder cleanup must never break a memory write
        return result
    return raw_args
