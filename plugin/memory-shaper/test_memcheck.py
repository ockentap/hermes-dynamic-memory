# Tests for memcheck — the hidden memory-relevance self-report.
#
# Copyright 2026 ockentap
# SPDX-License-Identifier: Apache-2.0
# Part of hermes-dynamic-memory.
#
# The claims under test are the ones that decide whether a keyword gets
# deleted: a `wrong` verdict is worthless unless the model named a real file
# and a word the user actually typed, and a `fact` is worthless unless it is
# literally in the topic file. Every test here is a version of "does the
# evidence survive checking".

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import memcheck
import memcheck_hooks


INDEX = """# index header

keyword,keyword,keyword → file.md
hermes,gateway,telegram,restart,systemd → gateway-restart.md
heater,thermostat,hvac,valve,radiator → thermostat-app.md
heater,boiler,protocol,pipe,pressure → boiler-service.md
"""

BODY_A = """# gateway restart

The gateway blocks restarting itself. Use `hermes gateway restart` from a shell,
never from inside the gateway process. The unit is hermes-gateway.service.
"""

ENTRIES = memcheck.parse_index(INDEX)


# ---------------------------------------------------------------- parsing

def test_split_tag_strips_trailer():
    text = "The answer is 42.\n\n<mc t=\"1\" opened=\"a.md\" rejected=\"null\" hook=\"gateway\">"
    visible, raw, misplaced = memcheck.split_tag(text)
    assert visible == "The answer is 42."
    assert "opened" in raw
    assert misplaced is False


def test_split_tag_records_text_after_tag():
    text = "Answer.\n<mc t=\"2\" verdict=\"ok\"></mc>\nHope that helps."
    visible, raw, misplaced = memcheck.split_tag(text)
    assert "Hope that helps." in visible
    assert misplaced is True
    assert raw is not None


def test_split_tag_absent_returns_original():
    text = "Just an answer with no tag."
    visible, raw, misplaced = memcheck.split_tag(text)
    assert visible == text and raw is None and misplaced is False


def test_parse_tag_nullish_and_case():
    s = memcheck.parse_tag('<mc t="2" verdict="OK" wrong="null" right="" hook=none>')
    assert s["verdict"] == "ok"
    assert s["wrong"] is None
    assert s["right"] is None
    assert s["hook"] is None


def test_parse_index_skips_template_and_markers():
    assert "file.md" not in ENTRIES
    assert "gateway-restart.md" in ENTRIES
    assert ENTRIES["gateway-restart.md"][:2] == ["hermes", "gateway"]
    marker = memcheck.parse_index("!!a,b,c → done.md")
    assert marker == {"done.md": ["a", "b", "c"]}


# ------------------------------------------------------------- validation

def test_hook_must_be_typed_and_on_the_line():
    assert memcheck.check_hook("gateway", ["restart the gateway please"], ["hermes", "gateway"])
    # Model blamed a word the user never typed.
    assert not memcheck.check_hook("systemd", ["restart the gateway"], ["hermes", "gateway"])
    # Word was typed but is not a keyword on that line.
    assert not memcheck.check_hook("restart", ["restart the gateway"], ["hermes", "gateway"])


def test_fact_must_be_verbatim():
    ok = "The gateway blocks restarting itself"
    assert memcheck.check_fact(ok, BODY_A)
    assert not memcheck.check_fact("the gateway cannot restart itself", BODY_A)
    assert not memcheck.check_fact("gateway blocks", BODY_A)  # under the word floor


def test_validate_flags_invented_file():
    sample = memcheck.parse_tag('<mc t="2" verdict="wrong" wrong="ghost.md" right="gateway-restart.md" hook="gateway">')
    problems = memcheck.validate(sample, ENTRIES, {}, ["restart gateway"])
    assert "unknown_file:ghost.md" in problems


def test_validate_wrong_needs_alternative():
    sample = memcheck.parse_tag('<mc t="2" verdict="wrong" wrong="thermostat-app.md" right="null" hook="heater">')
    problems = memcheck.validate(sample, ENTRIES, {}, ["heater is broken"])
    assert "wrong_without_alternative" in problems


def test_validate_untraceable_hook_is_not_evidence():
    # `gateway` is on the CORRECT line, not on the line that misfired, so it
    # cannot explain the misfire and must not be demoted.
    sample = memcheck.parse_tag(
        '<mc t="2" verdict="wrong" wrong="thermostat-app.md" right="gateway-restart.md" hook="gateway">')
    problems = memcheck.validate(sample, ENTRIES, {}, ["restart the gateway"])
    assert "hook_untraceable" in problems


def test_validate_hook_off_the_wrong_line_is_not_evidence():
    # `radiator` is on the thermostat line, but the user never typed it this turn.
    sample = memcheck.parse_tag(
        '<mc t="2" verdict="wrong" wrong="thermostat-app.md" right="gateway-restart.md" hook="radiator">')
    problems = memcheck.validate(sample, ENTRIES, {}, ["the gateway will not restart"])
    assert "hook_untraceable" in problems


def test_validate_clean_wrong_sample():
    sample = memcheck.parse_tag(
        '<mc t="2" verdict="wrong" wrong="thermostat-app.md" right="gateway-restart.md" hook="radiator">')
    # `radiator` is on the wrong line, the user typed it, and the correction names
    # the destination with one of its own keywords ("gateway"). Actionable shape.
    problems = memcheck.validate(sample, ENTRIES, {"gateway-restart.md": BODY_A},
                                 ["radiator does nothing on the AC",
                                  "no, I meant the gateway restart thing"])
    assert problems == []


def test_hook_must_be_one_keyword_not_a_phrase():
    # A phrase that merely contains a keyword is not a keyword: "daemon unit"
    # passed by substring and produced a demotion nobody could act on.
    assert not memcheck.check_hook("daemon unit", ["the daemon unit is dead"], ["daemon", "unit"])
    assert memcheck.check_hook("daemon", ["the daemon unit is dead"], ["daemon", "unit"])


def test_correction_must_name_the_destination():
    sample = memcheck.parse_tag(
        '<mc t="2" verdict="wrong" wrong="thermostat-app.md" right="gateway-restart.md" hook="radiator">')
    problems = memcheck.validate(sample, ENTRIES, {"gateway-restart.md": BODY_A},
                                 ["radiator does nothing", "no, the one from last Tuesday"])
    assert "correction_does_not_name_target" in problems


def test_validate_fact_not_in_file():
    sample = memcheck.parse_tag(
        '<mc t="2" verdict="ok" wrong="null" right="gateway-restart.md" hook="gateway" '
        'fact="the gateway restarts itself on tuesdays">')
    problems = memcheck.validate(sample, ENTRIES, {"gateway-restart.md": BODY_A}, ["gateway"])
    assert "fact_not_in_file" in problems


# --------------------------------------------------------------- routing

def test_prompt_terms_rejects_shared_words():
    terms = memcheck.prompt_terms("heater gateway radiator absurdlylongword", ENTRIES)
    # `heater` sits on two lines; `gateway` and `radiator` on one each.
    assert "heater" not in terms
    assert "radiator" in terms and "gateway" in terms


def test_prompt_terms_drops_stopwords_and_target_words():
    terms = memcheck.prompt_terms("please restart the gateway systemd", ENTRIES,
                                  target="gateway-restart.md")
    assert "please" not in terms and "restart" not in terms


def test_prompt_terms_keeps_identifiers():
    terms = memcheck.prompt_terms("the box at 192.168.0.10 and serda.ba", ENTRIES)
    assert "192.168.0.10" in terms or "192.168.0.10" in " ".join(terms)


# ----------------------------------------------------------------- turns

def test_human_turn_counts_prior_user_messages():
    hist = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    assert memcheck.human_turn(hist, True) == 1
    assert memcheck.human_turn([], True) == 1
    assert memcheck.human_turn(hist, False, "next") == 2
    # Current message already appended to history: still turn 2.
    hist2 = hist + [{"role": "user", "content": "next"}]
    assert memcheck.human_turn(hist2, False, "next") == 2


def test_injection_window():
    assert memcheck.injection_for_turn(1, {}) == "1"
    assert memcheck.injection_for_turn(2, {}) == "2"
    assert memcheck.injection_for_turn(4, {}) == "2"
    assert memcheck.injection_for_turn(5, {}) is None


def test_injection_stops_when_verdict_settled():
    assert memcheck.injection_for_turn(3, {"last_verdict": "ok", "last_asked_turn": 2}) is None
    assert memcheck.injection_for_turn(3, {"last_verdict": "wrong", "last_asked_turn": 2}) is None
    # One `unsure` is enough — do not re-ask on the next turn.
    assert memcheck.injection_for_turn(3, {"last_verdict": "unsure", "last_asked_turn": 2}) is None


def test_has_substance():
    assert not memcheck.has_substance("ok")
    assert not memcheck.has_substance("thanks!")
    assert memcheck.has_substance("the gateway will not restart")


# ---------------------------------------------------------------- scoring

def _sample(**kw):
    base = {"t": "2", "problems": [], "terms": [], "used_files": []}
    base.update(kw)
    return base


def test_score_is_asymmetric_and_ignores_invalid():
    samples = [
        _sample(verdict="wrong", wrong="thermostat-app.md", hook="heater"),
        _sample(verdict="wrong", wrong="thermostat-app.md", hook="heater"),
        _sample(verdict="ok", used_files=["gateway-restart.md"], terms=["radiator"]),
        _sample(verdict="ok", used_files=["gateway-restart.md"], terms=["radiator"]),
        _sample(verdict="ok", used_files=["gateway-restart.md"], terms=["bogus"],
                problems=["hook_untraceable"]),
        _sample(verdict="unsure"),
    ]
    rep = memcheck.score(samples)
    assert rep["samples"] == 6
    assert rep["ignored"] == 2
    assert rep["review"]["thermostat-app.md"]["heater"] == -4.0
    assert rep["promote"]["gateway-restart.md"] == {"radiator": 2.0}
    assert "bogus" not in rep["promote"].get("gateway-restart.md", {})


def test_hook_shared_flags_a_collision():
    # `heater` is on BOTH the thermostat line and the boiler line (see INDEX) and the
    # user typed it: that is a collision, not a bad keyword.
    assert memcheck.hook_shared("heater", ["thermostat-app.md"],
                                ["boiler-service.md"], ENTRIES, ["heater is slow"])
    # `radiator` is only on the thermostat line: a genuine one-sided miss.
    assert not memcheck.hook_shared("radiator", ["thermostat-app.md"],
                                    ["boiler-service.md"], ENTRIES, ["radiator is broken"])


def test_score_never_demotes_a_shared_hook():
    samples = [
        _sample(verdict="wrong", wrong="thermostat-app.md",
                right="boiler-service.md", hook="heater", hook_shared=True),
    ]
    rep = memcheck.score(samples)
    assert rep["review"] == {}
    assert rep["ambiguous_hooks"] == {"thermostat-app.md": 1}


# ------------------------------------------------------------ hook wiring

def _store(tmp_path: Path) -> Path:
    home = tmp_path / "hermes"
    mem = home / "memories"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text(INDEX, encoding="utf-8")
    (mem / "gateway-restart.md").write_text(BODY_A, encoding="utf-8")
    (mem / "thermostat-app.md").write_text("thermostat heater radiator\n", encoding="utf-8")
    return home


def test_pre_llm_call_injects_once(tmp_path, monkeypatch):
    home = _store(tmp_path)
    monkeypatch.setattr(memcheck_hooks, "_hermes_home", lambda: home)
    ctx = memcheck_hooks.pre_llm_call(
        session_id="s1", user_message="the gateway will not restart after a reboot",
        conversation_history=[], is_first_turn=True, platform="telegram")
    assert ctx and "<mc t=\"1\"" in ctx["context"]
    # Turn 2 gets the verdict tail.
    ctx2 = memcheck_hooks.pre_llm_call(
        session_id="s1", user_message="no, I meant the heater unit",
        conversation_history=[{"role": "user", "content": "the gateway will not restart"},
                              {"role": "assistant", "content": "..."}],
        is_first_turn=False, platform="telegram")
    assert ctx2 and "<mc t=\"2\"" in ctx2["context"]
    # A settled verdict stops the asking.
    memcheck_hooks.transform_llm_output(
        response_text='done <mc t="2" verdict="ok" wrong="null" right="null" hook="null" fact="null">',
        session_id="s1", platform="telegram", turn_id="t2")
    ctx3 = memcheck_hooks.pre_llm_call(
        session_id="s1", user_message="and another thing entirely",
        conversation_history=[{"role": "user", "content": "x"}] * 3,
        is_first_turn=False, platform="telegram")
    assert ctx3 is None


def test_transform_strips_and_logs_valid_sample(tmp_path, monkeypatch):
    home = _store(tmp_path)
    monkeypatch.setattr(memcheck_hooks, "_hermes_home", lambda: home)
    memcheck_hooks.pre_llm_call(session_id="s2", user_message="restart the gateway please",
                                conversation_history=[], is_first_turn=True, platform="telegram")
    out = memcheck_hooks.transform_llm_output(
        response_text=('Use `hermes gateway restart`.\n'
                       '<mc t="1" opened="gateway-restart.md" rejected="thermostat-app.md" hook="gateway">'),
        session_id="s2", platform="telegram", turn_id="t1")
    assert out == "Use `hermes gateway restart`."
    rec = json.loads(memcheck.samples_path(home).read_text(encoding="utf-8").splitlines()[-1])
    assert rec["opened"] == "gateway-restart.md"
    assert rec["problems"] == []


def test_transform_returns_none_without_tag(tmp_path, monkeypatch):
    home = _store(tmp_path)
    monkeypatch.setattr(memcheck_hooks, "_hermes_home", lambda: home)
    assert memcheck_hooks.transform_llm_output(response_text="plain answer",
                                               session_id="s3", platform="telegram") is None


def test_transform_is_still_stripped_when_validation_is_angry(tmp_path, monkeypatch):
    home = _store(tmp_path)
    monkeypatch.setattr(memcheck_hooks, "_hermes_home", lambda: home)
    out = memcheck_hooks.transform_llm_output(
        response_text='Answer.\n<mc t="2" verdict="banana" wrong="ghost.md">',
        session_id="s4", platform="telegram")
    assert out == "Answer."
    rec = json.loads(memcheck.samples_path(home).read_text(encoding="utf-8").splitlines()[-1])
    assert "bad_verdict" in rec["problems"]
    assert "unknown_file:ghost.md" in rec["problems"]
