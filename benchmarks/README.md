# Benchmarks

Everything needed to **reproduce or challenge** the numbers in
[`docs/complexity.md`](../docs/complexity.md), [`docs/cohort-50.md`](../docs/cohort-50.md)
and [`docs/compression.md`](../docs/compression.md).

No claim in this repo should be taken on trust. Every figure below can be
re-derived from the fixtures and scripts here, or disputed by reading the raw
transcripts.

## Model and versions used

All benchmarks in this repo were run under the same conditions. These are part of
the result, not incidentals — a different model would move the numbers, and the
`deepseek-chat` finding below is specific to this one.

| | |
|---|---|
| **Model** | `deepseek-chat` |
| **Provider** | `deepseek` |
| **Hermes version** | v0.21.3 |
| **Keeper images** | `hermes-native:0.21.3`, `hermes-dynmem:1.4.3` |
| **Native memory cap** | 2,200 characters |
| **Date** | 2026-09-19 |
| **Sessions** | one fresh session per question/probe; session state wiped before install |

Verify the model in any container before trusting a run:

```bash
docker exec clean-native bash -c 'grep -A2 "^model:" /root/.hermes/config.yaml'
# model:
#   default: deepseek-chat
#   provider: deepseek
```

**Two model-dependent caveats**, both recorded in the individual write-ups:

- `deepseek-chat` shows a strong preference for **local filesystem evidence over
  injected memory**. The clearest case is `pref_shell`: asked which shell the user
  uses, it answered `bash` by inspecting the container's own shell instead of
  reading the stored preference. This inflates dynamic's failure count.
- `deepseek-chat` already knows general facts like Kafka and Postgres, so early
  probes measuring recall of *well-known* facts measured the model, not the
  memory. The fixtures were rewritten to use facts the model cannot already know
  (`docs/benchmark.md`).

Results on other models are welcome — the fixtures and scripts are model-agnostic.

```
benchmarks/
  fixtures/                     the memories fed to both systems
    cohort50.json               50 distinct atomic memories
    complex_facts.json          6 verbose structured memories + their probes
  scripts/
    harness.py                  shared install / ask / grade / adjudicate
    run_cohort50.py             50 memories, 50 questions
    run_complexity.py           6 complex memories, 30 detail probes
  results/
    native-cap.json             which memories native's cap accepted vs refused
    cohort-50/
      answers-mechanical.json   regex scores, before human review
      answers-adjudicated.json  the published verdicts, with reasons
    complexity/
      answers-mechanical.json
      answers-adjudicated.json
```

## Quickest verification: re-score the committed answers

No containers, no API key, no cost. Reads the committed transcripts and re-tallies
them using the adjudicated verdicts:

```bash
python3 benchmarks/scripts/run_cohort50.py   --verify-only
# native  : 29/50
# dynamic : 46/50

python3 benchmarks/scripts/run_complexity.py --verify-only
# native  : 11/30
# dynamic : 30/30
#   native stored  : 11/11
#   native refused : 0/19
```

`answers-mechanical.json` is the raw regex output and `answers-adjudicated.json`
is what was published, with a `*_final_reason` field on every entry. Diff them to
see exactly which answers were overridden and why.

## Full re-run

Requires the two keeper images and a DeepSeek API key.

```bash
docker run -d --name clean-native  --hostname clean-native  \
    -e DEEPSEEK_API_KEY=...  hermes-native:0.21.3  sleep infinity
docker run -d --name clean-dynamic --hostname clean-dynamic \
    -e DEEPSEEK_API_KEY=...  hermes-dynmem:1.4.3   sleep infinity

python3 benchmarks/scripts/run_cohort50.py   --native clean-native --dynamic clean-dynamic
python3 benchmarks/scripts/run_complexity.py --native clean-native --dynamic clean-dynamic
```

Both scripts call `clean_container()` and `assert_clean()` **before** installing
anything. That is not defensive boilerplate — see below.

## Two things that will invalidate your run

**1. Session history contamination.** An earlier version of these benchmarks ran
on containers holding ~1,000 messages of setup conversation in `state.db`, so
questions were answered out of session history rather than memory. Native scored
84% on that run and 58% on the clean one. If you skip `assert_clean`, you are
measuring the database, not the memory.

**2. Leftover example files.** The repo ships `examples/memories/` fixtures. In the
original complexity run, two probes were answered from a stray
`examples/memories/deploy-pipeline.md` instead of the fixture under test. Prune
the container before installing, or you will score fabricated passes.

## Why grading is done by hand

The published verdicts come from **reading every failing transcript**, not from a
regex. That is not a stylistic choice — three automated graders were tried and
disagreed:

| grader | native | why it was wrong |
|---|---|---|
| substring match | 42/50 | **counted refusals as passes.** "I don't have that recorded — nothing there states a merge preference" scored as a pass for a rebase question, because it contains the words. |
| blanket refusal-regex | 28/50 | **failed true answers.** "Conversational — you picked it up living in Berlin. I have no formal level recorded" is correct, but reads as a denial. |
| refusal + affirmation check | 26/50 | better, still over-flagging |
| **manual adjudication** | **29/50** | every failing transcript read and called individually |

At that point tuning the grader until it produces a preferred number stops being
measurement. So `harness.py` scores mechanically, marks anything with a
`denial(` or `no-needle` reason as **needing review**, and `adjudicate()` applies
hand-written overrides that each carry a reason string. Those overrides are the
`ADJUDICATIONS` dicts at the top of each runner — audit them directly.

The general lesson, if you are benchmarking anything an LLM says: **a refusal and a
correct answer can be textually near-identical.** Grade on whether the model
asserted the fact, and read the disagreements.

## Known limitations of these benchmarks

- **n=1 per probe.** No repeats, no variance reported. `pref_shell` and
  `env_terminal` could be noise.
- **One model, one provider.** `deepseek-chat` shows a strong preference for local
  filesystem evidence over injected memory, which likely inflates dynamic's
  failure count (`pref_shell` answered from the container's own shell).
- **Synthetic user, synthetic facts.** Real memory is messier and less atomic.
- **Adjudication is human judgement.** Raw answers are committed precisely so the
  calls can be challenged.
- **The 12-keyword capacity figure is a projection**, not a measurement — the real
  index averaged 7 keywords and 82 chars per line. See the "Capacity projection"
  section of [`docs/complexity.md`](../docs/complexity.md).

## Adding a benchmark

Reuse `harness.py`. The three invariants worth keeping:

1. `clean_container()` then `assert_clean()` before installing.
2. One fresh session per question, raw answer written to disk unedited.
3. Mechanical score **plus** a reviewable reason, then explicit adjudication.

If a result cannot be re-derived from the committed files, it should not go in
the README.
