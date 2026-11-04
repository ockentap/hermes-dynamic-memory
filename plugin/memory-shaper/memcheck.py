# memcheck — hidden memory-relevance self-report
#
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory — https://github.com/ockentap/hermes-dynamic-memory
#
# The index is injected as text and the model does the routing, so the only
# cheap ground truth about a routing decision is the model's own account of it.
# This module asks for that account in a tagged trailer, strips the trailer
# before the reply is stored or shown, and keeps every claim checkable:
#
#   * a filename must exist in the index            (else: invented)
#   * `hook` must appear in the user's own messages AND on that line's keywords
#   * `fact` must be a verbatim substring of the topic file body
#
# A sample that fails a check is recorded with its problems and MUST NOT be
# used to change the store. That is the whole point: the model's causal
# attribution is the least reliable claim here, so it has to earn the right to
# demote a keyword.
#
# Pure stdlib, no Hermes imports. The plugin owns the hooks; every decision
# lives here so it can be tested without an agent.

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path

# --------------------------------------------------------------------------
# Injection text
# --------------------------------------------------------------------------

# Turn 1 asks for observables only: at that point the user has not reacted yet,
# so "was this the right memory" is not answerable and asking it invites a
# fabricated yes. What IS available is what the model did not read: rejected
# and near-miss files never show up in the tool log, and they are exactly the
# false-attraction events that identify an over-broad keyword.
T1_TEMPLATE = (
    "[memcheck t1] When your answer is complete, append exactly one line after everything else:\n"
    '<mc t="1" opened="" rejected="" hook="">\n'
    "opened = the memory file(s) you read for this request, comma-separated; "
    "rejected = any file you nearly read, or that competed with the one you chose; "
    'hook = the single word from my message that most attracted you to that line. '
    "Use null for all three when nothing was opened or considered. Real filenames only. "
    "Nothing outside the tag."
)

# Turns 2-4: now the user has spoken, so a verdict is meaningful. `unsure` is
# the pressure valve; without it a model with no signal answers `ok` and the
# corpus fills with meaningless positives.
T2_TEMPLATE = (
    "[memcheck t2] When your answer is complete, append exactly one line after everything else:\n"
    '<mc t="2" verdict="" wrong="" right="" hook="" fact="">\n'
    "verdict = ok if the memory you used still fits what I am asking; wrong if I corrected you, "
    "changed topic, or asked for something that memory does not cover; unsure if I gave no signal "
    "either way - answer unsure rather than guessing.\n"
    "wrong = the file that misfired; right = the file that should have routed instead "
    "(real filenames or null).\n"
    "hook = the exact word from my earlier message that pulled you toward the wrong file, or null.\n"
    "fact = 8-15 words copied verbatim from the memory you relied on, or null.\n"
    "One line only. Nothing outside the tag."
)

DEFAULT_TURN_MIN = 1
DEFAULT_TURN_MAX = 4
_T1_ONLY_TURN = 1

# Platforms where there is no human reading the reply, or where the reply is
# machine-consumed: a hidden tail is noise there and the turn counter is not a
# conversation.
SKIP_PLATFORMS = {"cron", "subagent", "oneshot", "batch"}

INDEX_NAME = "MEMORY.md"
STATE_DIRNAME = "state"
STATE_SUBDIR = "memcheck"
STATE_FILE = "state.json"
SAMPLES_FILE = "samples.jsonl"

# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

_MC_ELEMENT_RE = re.compile(r"<mc\b[^<>]*>(?:\s*</mc>)?", re.IGNORECASE)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_NULLISH = {"", "null", "none", "nil", "n/a", "na", "-", "unknown"}

_ARROW_SPLIT_RE = re.compile(r"\s*(?:→|->)\s*")

_TOKEN_RE = re.compile(r"[0-9a-z][0-9a-z_.\-/]{4,}")

# Merged English / BCS / Swedish function words. Folding accents turns `š` into
# `s`, so the forms here are folded too. Anything shorter than five characters
# is already excluded by _TOKEN_RE.
STOPWORDS = {
    "about", "above", "after", "again", "against", "almost", "already", "also",
    "although", "always", "among", "another", "answer", "anything", "around",
    "because", "before", "behind", "being", "below", "beside", "better", "between",
    "beyond", "came", "cannot", "could", "does", "doing", "done", "down", "during",
    "each", "either", "else", "enough", "even", "ever", "every", "from", "further",
    "gave", "give", "goes", "going", "gone", "have", "having", "here", "hers",
    "herself", "himself", "into", "itself", "just", "keep", "kept", "know",
    "known", "last", "later", "least", "less", "like", "made", "make", "many",
    "maybe", "might", "more", "most", "much", "must", "near", "need", "never",
    "next", "none", "nothing", "often", "once", "only", "other", "others",
    "ought", "over", "perhaps", "please", "quite", "rather", "really", "right",
    "said", "same", "should", "since", "some", "something", "still", "such",
    "sure", "take", "than", "that", "their", "them", "themselves", "then",
    "there", "these", "they", "thing", "things", "this", "those", "though",
    "through", "thus", "time", "today", "together", "told", "tomorrow", "took",
    "actually", "asking", "basically", "entire", "instead", "literally", "meant",
    "sorry", "supposed", "thinking", "thought", "totally", "wanted", "whole",
    "toward", "under", "until", "upon", "very", "want", "wants", "well", "were",
    "what", "when", "where", "whether", "which", "while", "with", "within",
    "without", "would", "your", "yours", "yourself",
    # BCS
    "ako", "ali", "bih", "bila", "bile", "bilo", "bio", "bismo", "biste", "biti",
    "budem", "cak", "casa", "dakle", "dana", "dobar", "dobro", "dok", "drugo",
    "gdje", "govori", "htio", "htjela", "idem", "imas", "imati", "imamo", "ipak",
    "izmedju", "jedan", "jedna", "jedno", "jeste", "jos", "kada", "kako", "koga",
    "koja", "koje", "koji", "kroz", "ljudi", "mene", "meni", "mislim", "mnogo",
    "mogu", "moze", "mozda", "mozes", "nacin", "nama", "nase", "nasi", "nego",
    "neki", "neko", "nema", "nemam", "nije", "nijedan", "onda", "opet", "osim",
    "ovako", "ovdje", "ovaj", "ovo", "pak",    "pitala", "pitanje",
    "pokusaj", "posle", "posto", "prema", "prije", "prosli", "radi", "sada",
    "samo", "sam", "smo", "sta", "steta", "stvar", "stvari", "sve", "svaki",
    "svakako", "tako", "tamo", "tebe", "tebi", "treba", "trebam", "tvoj", "uvijek",
    "vama", "vase", "vec", "veoma", "vise", "zato", "zeli", "zelim", "znaci",
    # Swedish
    "alltsa", "anda", "annan", "annat", "annars", "aven", "bara", "battre",
    "blev", "blir", "blivit", "borde", "darfor", "denna", "deras", "dessa",
    "detta", "efter", "eller", "enligt", "fanns", "fick", "finns", "flera",
    "foljande", "fram", "ganska", "gjorde", "gorna", "hade", "har", "heller",
    "hitta", "hur", "ihop", "inga", "ingen", "inom", "inte", "just", "kanske",
    "kommer", "kunna", "lamnar", "later", "man", "medan", "menar", "mera",
    "mesta", "mycket", "nagon", "nagot", "nara", "nasta", "naste", "nog", "ocksa",
    "plats", "redan", "samma", "sedan", "senare", "sista", "skall", "skulle",
    "sluta", "snabbt", "spelar", "stallet", "tack",
    "talar", "tanke", "tiden", "tills", "tycker", "under", "uttryck", "vagen",
    "valdigt", "veta", "viktigt", "vilka", "vilken", "vilket", "visa", "visar",
    "vilja", "villa", "vore", "soker", "sokt",
}


def fold(text: str) -> str:
    """NFKD-fold and casefold. `č/ć/š/ž/å/ä/ö` collapse to plain ASCII."""
    if not text:
        return ""
    norm = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in norm if not unicodedata.combining(ch))
    return stripped.casefold()


def parse_attrs(raw: str) -> dict[str, str]:
    """Pull `k="v"` pairs out of one tag. Unknown keys are kept for logging."""
    out: dict[str, str] = {}
    for key, value in _ATTR_RE.findall(raw or ""):
        v = value.strip()
        out[key.lower()] = v
    return out


def _nullish(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if fold(v) in _NULLISH:
        return None
    return v


def split_tag(text: str) -> tuple[str, str | None, bool]:
    """Return ``(visible_text, last_raw_tag, misplaced)``.

    Every ``<mc …>`` element is removed; the LAST one is the data carrier.
    ``misplaced`` is True when text followed the tag, which is a compliance
    miss worth recording but never worth hiding the user's real answer for.
    """
    if not text:
        return text, None, False
    matches = list(_MC_ELEMENT_RE.finditer(text))
    if not matches:
        return text, None, False
    last = matches[-1]
    misplaced = bool(text[last.end():].strip())
    visible = _MC_ELEMENT_RE.sub("", text)
    visible = re.sub(r"[ \t]+\n", "\n", visible)
    visible = re.sub(r"\n{3,}", "\n\n", visible).strip()
    return visible, last.group(0), misplaced


def parse_tag(raw_tag: str) -> dict:  # heterogeneous: strings plus used_files
    attrs = parse_attrs(raw_tag or "")
    return {
        "t": _nullish(attrs.get("t")),
        "opened": _nullish(attrs.get("opened")),
        "rejected": _nullish(attrs.get("rejected")),
        "verdict": (_nullish(attrs.get("verdict")) or "").lower() or None,
        "wrong": _nullish(attrs.get("wrong")),
        "right": _nullish(attrs.get("right")),
        "hook": _nullish(attrs.get("hook")),
        "fact": _nullish(attrs.get("fact")),
    }


def parse_index(text: str) -> dict[str, list[str]]:
    """Parse index lines into ``{target.md: [keyword, …]}``.

    Tolerates ASCII arrows on read (writes are the guard's business), skips
    marker lines' leading `!`, and drops the template line so it is never a
    valid target.
    """
    entries: dict[str, list[str]] = {}
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        body = s.lstrip("!")
        if "→" not in body and "->" not in body:
            continue
        parts = _ARROW_SPLIT_RE.split(body, maxsplit=1)
        if len(parts) != 2:
            continue
        kw_blob, target = parts
        target = target.strip().strip("`").strip()
        if not target.endswith(".md"):
            continue
        kws = [k.strip() for k in kw_blob.split(",") if k.strip()]
        if len(kws) < 2:
            # A single bare word before the arrow is prose, not an entry.
            continue
        if target == "file.md" and {fold(k) for k in kws} <= {"keyword"}:
            continue
        entries[target] = [fold(k) for k in kws]
    return entries


def keyword_owners(entries: dict[str, list[str]]) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = {}
    for target, kws in entries.items():
        for kw in kws:
            owners.setdefault(kw, set()).add(target)
    return owners


def split_targets(value) -> list[str]:
    """Accept a comma string or an already-split list (records store both)."""
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in re.split(r"[,;]", str(value)) if p.strip()]


# --------------------------------------------------------------------------
# Validation — every claim has to be checkable
# --------------------------------------------------------------------------

def check_filename(name: str, entries: dict[str, list[str]]) -> bool:
    base = os.path.basename(name.strip())
    return base in entries


def check_hook(hook: str, user_messages: list[str], keywords: list[str]) -> bool:
    """`hook` must be a word the user actually typed AND a keyword on that line."""
    if not hook:
        return False
    h = fold(hook).strip().strip(".,!?;:\"'()[]")
    if not h:
        return False
    if not any(h in fold(m) for m in user_messages or []):
        return False
    for kw in keywords or []:
        k = fold(kw)
        if k == h or h in k or k in h:
            return True
    return False


def check_fact(fact: str, body: str, min_words: int = 5) -> bool:
    """`fact` must be a verbatim-ish substring of the topic file."""
    if not fact or not body:
        return False
    f = fold(fact).strip().strip("\"'`.,;:")
    f = re.sub(r"\s+", " ", f)
    if len(f.split()) < min_words:
        return False
    b = re.sub(r"\s+", " ", fold(body))
    return f in b


def validate(sample: dict, entries: dict[str, list[str]], bodies: dict[str, str],
             user_messages: list[str]) -> list[str]:
    """Return a list of problems; empty means the sample is usable as evidence."""
    problems: list[str] = []
    kind = sample.get("t")
    opened = split_targets(sample.get("opened"))
    rejected = split_targets(sample.get("rejected"))
    wrong = split_targets(sample.get("wrong"))
    right = split_targets(sample.get("right"))

    for name in opened + rejected + wrong + right:
        if not check_filename(name, entries):
            problems.append(f"unknown_file:{os.path.basename(name)}")

    if kind == "2":
        verdict = sample.get("verdict")
        if verdict not in {"ok", "wrong", "unsure"}:
            problems.append("bad_verdict")
        if verdict == "wrong":
            if not wrong:
                problems.append("wrong_without_file")
            if not right:
                problems.append("wrong_without_alternative")
        if sample.get("hook"):
            # On a `wrong` verdict the blamed word must be a keyword ON THE
            # WRONG LINE and must be a word the user typed. A word that only
            # appears on the correct line explains nothing about the misfire,
            # and demoting it would delete a good keyword on the model's say-so.
            if verdict == "wrong":
                blame = [f for f in wrong if f in entries]
            else:
                blame = [f for f in (wrong + right + opened) if f in entries]
            if not blame:
                problems.append("hook_without_file")
            elif not any(check_hook(sample["hook"], user_messages, entries.get(f, [])) for f in blame):
                problems.append("hook_untraceable")
        if sample.get("fact"):
            # `fact` is quoted from the memory the model RELIED on, which on a
            # wrong verdict is the misfiring file, not the correct one.
            candidates = wrong + right + opened + split_targets(sample.get("used_files"))
            owners = [f for f in candidates if f in bodies]
            if not owners:
                problems.append("fact_without_file")
            elif not any(check_fact(sample["fact"], bodies.get(f, "")) for f in owners):
                problems.append("fact_not_in_file")

    if kind == "1":
        # Opening nothing is a legitimate outcome, not a fault: most turns do
        # not need a topic file. The t1 sample never votes in score() anyway —
        # it is there for `rejected` (near-miss files) and for `last_opened`.
        if sample.get("hook") and not (rejected or opened):
            problems.append("hook_without_file")

    return problems


# --------------------------------------------------------------------------
# Scoring — asymmetric on purpose
# --------------------------------------------------------------------------

WEIGHT_WRONG = -2.0   # a bad keyword costs more than a missing one
WEIGHT_OK = 1.0
PROMOTE_AT = 2.0
DEMOTE_AT = -2.0


def score(samples: list[dict]) -> dict:
    """Fold validated samples into per-keyword evidence.

    Only samples with no problems vote. `unsure` votes for nothing: it is the
    absence of a signal, not a positive.
    """
    demote: dict[str, dict[str, float]] = {}
    promote: dict[str, dict[str, float]] = {}
    ignored = 0
    for s in samples:
        if s.get("problems"):
            ignored += 1
            continue
        verdict = (s.get("verdict") or "").lower()
        if s.get("t") != "2" or verdict not in {"ok", "wrong"}:
            ignored += 1
            continue
        if verdict == "ok":
            # `used_files` is what the turn actually read (carried over from the
            # turn-1 observables tag); `right` covers a corrected turn.
            for f in split_targets(s.get("used_files") or s.get("right")):
                for term in s.get("terms") or []:
                    promote.setdefault(f, {}).setdefault(term, 0.0)
                    promote[f][term] += WEIGHT_OK
        else:
            hook = fold(s.get("hook") or "")
            for f in split_targets(s.get("wrong")):
                if hook:
                    demote.setdefault(f, {}).setdefault(hook, 0.0)
                    demote[f][hook] += WEIGHT_WRONG
            for f in split_targets(s.get("right")):
                for term in s.get("terms") or []:
                    promote.setdefault(f, {}).setdefault(term, 0.0)
                    promote[f][term] += WEIGHT_OK

    return {
        "samples": len(samples),
        "ignored": ignored,
        "used": len(samples) - ignored,
        "demote": {f: kept for f, d in demote.items()
                   if (kept := {k: v for k, v in d.items() if v <= DEMOTE_AT})},
        "promote": {f: kept for f, d in promote.items()
                    if (kept := {k: v for k, v in d.items() if v >= PROMOTE_AT})},
    }


# --------------------------------------------------------------------------
# Prompt-term candidates — uniqueness is the point
# --------------------------------------------------------------------------

def prompt_terms(message: str, entries: dict[str, list[str]], target: str | None = None,
                 limit: int = 8) -> list[str]:
    """Words the user typed that could route this line, and nothing else.

    Rules, in order of importance:
      1. never a word already on >= 2 lines — that buys matches and pays in
         ambiguity, which is the failure this whole feature exists to avoid;
      2. never a word already on the target line — no-op;
      3. never a function word, in any of the three languages this user mixes;
      4. keep identifiers (`192.168.0.10`, `v2026.9.14`, `serda.ba`) which the
         token regex already allows to carry a dot, dash, slash or underscore.
    """
    owners = keyword_owners(entries)
    seen: set[str] = set()
    out: list[str] = []
    for token in _TOKEN_RE.findall(fold(message or "")):
        if token in seen:
            continue
        seen.add(token)
        if token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        if len(token) < 5:
            continue
        holders = owners.get(token, set())
        if len(holders) >= 2:
            continue
        if target and target in holders:
            continue
        out.append(token)
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------
# State and sample storage
# --------------------------------------------------------------------------

def state_dir(home: Path) -> Path:
    return Path(home) / STATE_DIRNAME / STATE_SUBDIR


def _config_path(home: Path) -> Path:
    return state_dir(home) / STATE_FILE


def samples_path(home: Path) -> Path:
    return state_dir(home) / SAMPLES_FILE


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_state(home: Path) -> dict:
    p = _config_path(home)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def save_state(home: Path, state: dict) -> None:
    try:
        _atomic_write(_config_path(home), state)
    except Exception:
        pass  # state is an optimisation; never break a turn for it


def session_state(state: dict, session_id: str) -> dict:
    sess = state.get(session_id)
    if not isinstance(sess, dict):
        sess = {}
    sess.setdefault("msgs", [])
    sess.setdefault("last_verdict", None)
    sess.setdefault("last_asked_turn", 0)
    return sess


def remember_message(sess: dict, message: str, keep: int = 4) -> None:
    msgs = [m for m in sess.get("msgs", []) if isinstance(m, str)]
    if message and (not msgs or msgs[-1] != message):
        msgs.append(message)
    sess["msgs"] = msgs[-keep:]


def append_sample(home: Path, record: dict) -> None:
    p = samples_path(home)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # a failed log must never break the reply


# --------------------------------------------------------------------------
# Turn accounting
# --------------------------------------------------------------------------

def human_turn(history, is_first_turn: bool, user_message: str = "") -> int:
    """1-based index of the user message being answered right now.

    `conversation_history` may or may not already contain the current message,
    depending on the caller, so the current text is skipped when present.
    """
    if is_first_turn:
        return 1
    count = 0
    for msg in history or []:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            count += 1
            continue
        if user_message and content.strip() == user_message.strip():
            continue
        count += 1
    return count + 1


def has_substance(message: str, min_tokens: int = 2) -> bool:
    """Skip the tag for `ok`, `thanks`, `hey` — nothing to route."""
    tokens = [t for t in _TOKEN_RE.findall(fold(message or "")) if t not in STOPWORDS]
    return len(tokens) >= min_tokens


def injection_for_turn(turn: int, sess: dict, turn_min: int = DEFAULT_TURN_MIN,
                       turn_max: int = DEFAULT_TURN_MAX) -> str | None:
    """Decide whether this turn gets a tag, with early stop on a settled verdict.

    Turn 1 always gets the observables tag. Turns 2..max get the verdict tag,
    but only until one arrives: re-asking a settled question wastes the user's
    tokens and teaches the model to invent variation.
    """
    if turn < turn_min or turn > turn_max:
        return None
    if turn == _T1_ONLY_TURN:
        return "1"
    if sess.get("last_verdict") in {"ok", "wrong"}:
        return None
    if sess.get("last_asked_turn") == turn - 1 and sess.get("last_verdict") == "unsure":
        # One unsure is enough; a second ask rarely changes the answer.
        return None
    return "2"


def build_context(kind: str) -> str:
    return T1_TEMPLATE if kind == "1" else T2_TEMPLATE
