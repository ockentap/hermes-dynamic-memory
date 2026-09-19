# Complexity benchmark: do verbose, structured memories survive?

Run: 2026-09-19 · Hermes v0.21.3 · **model `deepseek-chat` via provider `deepseek`** · clean containers, one fresh session per probe

## Why this test exists

The 50-memory cohort used **atomic one-line facts**, and native stored all 28 that
fitted **verbatim** — so that run did not test compression at all. It tested
count.

Real memories are not one-liners. They are decisions with reasoning, exceptions,
ordering constraints, and names: the shape that a lossy summary destroys while
keeping the headline. These probes separate *"stored the gist"* from *"stored the
memory"*.

## Design

Six deliberately complex facts, each with a headline plus details a summary would
drop:

| fact | headline | details probed |
|---|---|---|
| expand/contract migration policy | backward-compatible, before deploy | one-release gap, NOT NULL rule, prod-snapshot test, forward-only, named approver |
| incident severity definitions | sev-1 = data loss/outage | 10-min commander, 30-min exec notice, 5-day postmortem, 3 sev-3 escalation |
| deploy ordering | migrate then canary | 0.5%/400ms thresholds, 20+10 min holds, roll back code not migration, separate cleanup release |
| production access control | read via replica | 90-day write grant, break-glass paging, 3-use freeze, contractor ban |
| retention matrix | audit logs 7 years | PII/backup 90-day rule, legal exemption, 13-month metrics |
| on-call escalation | primary → secondary → manager | 5-min page, CTO+auto-sev-1 at 30 min, 7-day fatigue cap, day off after 4h sev-1 |

Each detail probed as its own question. 30 probes per agent.

## Result

| | native | dynamic |
|---|---|---|
| detail recall (30 probes) | **11/30 (37%)** | **30/30 (100%)** |

Split by whether native could store the fact:

| native | detail recall |
|---|---|
| facts that FIT the cap (2 of 6) | **11/11 (100%)** |
| facts the cap REFUSED (4 of 6) | **0/19 (0%)** |

## The finding: loss is total, not gradual

Native stored **2 of 6** complex facts (1,615 of 2,200 chars). The other four were
refused outright. On the two it kept, it recalled **every** detail — 11 of 11,
including the named approver and the 7-day snapshot rule.

On the four it could not store, it recalled **nothing**. Not degraded, not
partial: zero.

That is the shape of the problem. Native's compression is not a graceful quality
degradation where you lose the fine print. It is a **hard cutoff**: entire
memories are either fully present or entirely absent, and which ones depends only
on what order they arrived in.

**Resident cost comparison:** native spent 1,615 chars to hold 2 complex facts.
Dynamic spent **503 chars** and held all 6, with full detail on disk.

## Adjudication note

Three native answers initially scored as passes on refused facts and were
**manually overturned**:

- two (`c3_deploy_ordering`) were answered from a *leftover example file*
  (`examples/memories/deploy-pipeline.md`) from an earlier run, not from the
  complex fact;
- one (`c5_retention_matrix`) explicitly disclaimed itself: *"this is the general
  answer, not a quote of your policy."*

Without that correction native would have scored 14/30 instead of 11/30, and the
"0/19" would have read "3/19". Raw transcripts are committed.

## Capacity projection (for the README charts)

The capacity figures used in the README are partly a **projection**, and the basis
matters:

| | chars per entry | complex memories in 2,200 chars |
|---|---|---|
| native (measured) | 808 | **2.7** |
| dynamic, 12 keys/entry (projected) | 131 | **16.8** |
| dynamic, as actually built (7 keys/entry, measured) | 82 | **26.8** |

The 12-keyword figure is a **stated upper bound**, not a measurement. The real
index built for this benchmark averaged **7 keywords and 82 chars per line**:

```
88 chars: migration,schema,rollback,backward-compatible,expand,contract → cx_c1_...
77 chars: severity,sev,incident,escalation,postmortem,page → cx_c2_incident_...
84 chars: deploy,canary,rollout,promote,threshold,rollback,ordering → cx_c3_depl...
```

Average measured keyword length is 7.6 chars, and the 12-keyword line assumes:
`12 x 7.6` keywords `+ 11` commas `+ 4` for the arrow `+ 25` filename = **131 chars**.

So the README's **6.2x** is the conservative claim. At the density actually
measured it would be **9.9x**. The lower figure is used deliberately: it holds even
if every entry uses the maximum keyword allowance.

## Limitations

1. **n=1 per probe.** No repeats.
2. **The 4 refused facts were never in native's memory**, so 0/19 is partly
   definitional — it measures the cap, not retrieval. The informative number is
   **11/11 on stored facts**: when native *can* hold a complex fact, it holds it
   completely.
3. **A leftover file contaminated two answers.** Future runs need a pruned
   container with no example fixtures present.
4. **One model, one day.**

## What this establishes

- **Native's ceiling is count, not depth.** It does not partially store complex
  memories — it stores some completely and loses the rest completely.
- **Dynamic reaches 3x the complex facts at 31% of the resident cost**, with
  every probed detail intact.
- **Predicting native's behaviour is easy and bleak:** whatever arrives after the
  cap fills is gone, regardless of importance. The migration policy and incident
  severity definitions survived only because they were fed first.

This is the strongest result in the project so far, and the first where the
difference is categorical rather than incremental.
