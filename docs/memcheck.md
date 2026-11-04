# memcheck — asking the router how it routed

The index is injected as text and the **model** does the routing. Nothing parses
the arrows at query time, so there is no router to log and no score to inspect.
The only cheap ground truth about a routing decision is the model's own account
of it — as long as every claim in that account can be checked.

`memcheck` asks for the account in a tagged trailer, strips the trailer before
the reply is stored or shown, and keeps only the claims that survive
verification. It never edits the index itself: it produces evidence, and the
optimization pass decides.

Shipped in `memory-shaper` 1.6.0. Two plugin hooks, **no core patch**.

| Hook | Where it runs | What it does |
|---|---|---|
| `pre_llm_call` | `agent/turn_context.py` → `build_api_messages` | returns `{"context": …}`; the host appends it to the **API-bound copy** of the user message only, so it never reaches SQLite |
| `transform_llm_output` | `agent/turn_finalizer.py` → `apply_llm_output_transform` (**before** the assistant row is first persisted, #44239) | strips the tag and returns the clean text, so the stored and replayed reply is the clean one |

Both properties are load-bearing: the tag must not inflate the stored transcript
(prompt-cache prefix + token bill), and it must not become corpus for the
keyword miner — the words `prompt`, `memory` and `hidden` would otherwise start
competing for slots in the index they are auditing.

## What gets asked, and when

Turn 1 gets observables only. The user has not reacted yet, so "was this the
right memory" is unanswerable and asking it invites a fabricated yes. What *is*
available is what the model did **not** read: `rejected` and near-miss files
never appear in the tool log, and they are the only visible record of a false
attraction before anyone complains.

```
[memcheck t1] When your answer is complete, append exactly one line after everything else:
<mc t="1" opened="" rejected="" hook="">
opened = the memory file(s) you read for this request, comma-separated; rejected =
any file you nearly read, or that competed with the one you chose; hook = the single
word from my message that most attracted you to that line. Use null for all three
when nothing was opened or considered. Real filenames only. Nothing outside the tag.
```

Turns 2–4 get the verdict, because now the user has spoken:

```
[memcheck t2] When your answer is complete, append exactly one line after everything else:
<mc t="2" verdict="" wrong="" right="" hook="" fact="">
verdict = ok if the memory you used still fits what I am asking; wrong if I corrected
you, changed topic, or asked for something that memory does not cover; unsure if I gave
no signal either way - answer unsure rather than guessing.
wrong = the file that misfired; right = the file that should have routed instead
(real filenames or null).
hook = the exact word from my earlier message that pulled you toward the wrong file, or null.
fact = 8-15 words copied verbatim from the memory you relied on, or null.
One line only. Nothing outside the tag.
```

`unsure` is the pressure valve. Without an explicit no-signal option a model
with no signal answers `ok`, and the corpus fills with meaningless positives.

**Early stop.** Ask at turn 2; if the answer is `unsure`, do not re-ask. Do not
ask again after `ok` or `wrong`. A settled question asked three times wastes the
user's tokens and teaches the model to invent variation. Turns 3–4 exist only
to catch the correction that arrives late.

## Three checks, and what they reject

| Claim | Check | Rejection |
|---|---|---|
| `opened` / `rejected` / `wrong` / `right` | basename exists in the index | `unknown_file:<name>` |
| `hook` | appears in one of the last 4 user messages **and** is a keyword **on the wrong line** | `hook_untraceable` |
| `fact` | ≥ 5 words, NFKD-folded, verbatim substring of the topic file | `fact_not_in_file` |
| `verdict` | one of `ok` / `wrong` / `unsure`; `wrong` needs both files | `bad_verdict`, `wrong_without_file`, `wrong_without_alternative` |

The `hook` rule is the one that matters. The model's causal attribution ("this
word pulled me") is the least reliable claim in the whole scheme, so it is
required to name a word the user actually typed **and** one that sits on the
line that misfired. A word that only appears on the *correct* line explains
nothing and demoting it would delete a good keyword on the model's say-so.

Any sample with a problem is recorded with its problems and **never votes**.
The raw tag is kept in the sample record so a rejected claim can be audited
later.

## Scoring

Asymmetric on purpose: a bad keyword costs more than a missing one.

- `ok` → **+1** per candidate term on the file that was used
- `wrong` (validated) → **−2** for the blamed keyword on the misfiring line, **+1** per candidate term on `right`
- `unsure` → nothing
- any problem → ignored entirely

Promotion needs **two independent clean positives**; demotion needs **one**
validated miss. Promotion candidates come from `prompt_terms()`, which enforces
the uniqueness rule the whole feature exists to serve:

1. never a word already on **≥ 2** lines — that buys matches and pays in
   ambiguity, which is the failure mode that makes the model read the wrong
   file;
2. never a word already on the target line;
3. never a function word (English, BCS and Swedish are all folded and dropped —
   `je`, `da`, `se`, `inte`, `ingen` cannot become keywords);
4. identifiers keep their punctuation: `192.168.0.10`, `serda.ba`,
   `v2026.9.14` survive the token regex.

## Files

| Path | Purpose |
|---|---|
| `~/.hermes/state/memcheck/state.json` | per-session ring buffer of the last 4 user messages, ask counters, last verdict |
| `~/.hermes/state/memcheck/samples.jsonl` | one record per returned tag; append-only |

Both are dot-state, deliberately **not** in `memories/` — the memories directory
is scanned by the orphan/index validators and mined for keyword candidates.

## Running it

```bash
python3 scripts/memcheck_report.py                 # ~/.hermes
python3 scripts/memcheck_report.py --home <dir>    # a test store
python3 scripts/memcheck_report.py --json
```

Report shape:

```
samples: 2  usable: 0  ignored: 2
  turn-1 observables asked    1  answered    1  compliance 100%
  verdict tail       asked    1  answered    1  compliance 100%
  verdicts: wrong=1
rejected claims: hook_untraceable=1
near-miss files (turn-1 rejected — review the hook word):
  aklima-android-app.md  ×1  hooks: daemon×1
```

`compliance` is the first number to read. A silent monitor and a healthy one
look identical without it: if `asked` climbs and `answered` does not, the model
is dropping the tag or the transform is not reaching the reply, and nothing
below it means anything.

Disable without uninstalling: `MEMCHECK_DISABLED=1`.

Platforms `cron`, `subagent`, `oneshot`, `batch` are skipped — no human reads
the reply, and the turn counter there is not a conversation.

## What it will change in the index (and what it will not)

Nothing, in this version. The report prints recommendations:
`demote` (validated misses) and `promote` (2+ clean positives). Applying them is
the optimizer's job, with the provenance sidecar recording `source: "prompt"`.

Rule for the applier, not negotiable: **prompt-derived keywords go in the free
zone, never the locked block.** The locked five are positional and permanent so
they hold on a store that never ran the optimizer; prompt words are the most
provisional thing in the system — they arrive with one conversation's vocabulary
and must expire. Cap 2 per line, decay after 60 days unused.

## Known limits

- **Attribution is weak evidence.** The model can name the wrong word with full
  confidence. That is why a miss is recorded but only a *traceable* one demotes,
  and why one miss is enough to demote but two positives are needed to promote.
- **One sample is not a measurement.** The report is designed to be read over
  dozens of sessions; a `demote` from a single session is a hint.
- **The `fact` check is substring matching.** A model that paraphrases will fail
  it and be discarded — the correct failure direction, since the alternative is
  accepting invented evidence.
- **Streaming.** `transform_llm_output` runs before persistence, and Hermes
  handles a post-stream rewrite (`transformed_final` in the api_server routes,
  `test_transformed_stream_output`). If a platform pushes deltas to the user
  faster than the transform resolves, the tag can be briefly visible; measure
  compliance on that platform before trusting it there.
