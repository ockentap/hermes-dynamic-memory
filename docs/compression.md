# Compression and capacity: measured numbers

Companion to [`benchmark.md`](benchmark.md). Every figure below is measured from
the real fixtures in that run, not modelled, except where marked **arithmetic**.

Run: 2026-09-19 · Hermes v0.21.3 · **model `deepseek 4.1 flash`** (provider `deepseek`; configured as `deepseek-chat`) · native cap 2,200 chars

## 1. Resident compression

Same facts, same session, two encodings:

| corpus | native resident | dynamic resident | compression |
|---|---|---|---|
| 3 private facts | 1,813 chars | 285 chars | **6.4x smaller** |
| 12 topics | 2,200 chars | 879 chars | **2.5x smaller** |

**Cite 6.4x** — it is the fair comparison, with identical facts on both sides.

The 2.5x figure understates the difference: native's 2,200 chars bought only
**11 of 12 topics** (the twelfth was refused by the cap), while dynamic fit all
12 into 879 chars — 40% of the space for more coverage.

### Why the compression is real, not just deferred work

| | what one resident char buys |
|---|---|
| native | 1.0 char of fact — the block *is* the memory |
| dynamic | **12–18 chars** of reachable content — each char addresses a file |

Measured: 3,321 chars reachable from 285 resident (12x); 15,834 chars reachable
from 879 resident (18x).

## 2. Entry capacity in one 2,200-char budget

Per-entry cost, measured:

| | chars/entry | source |
|---|---|---|
| dynamic index line | 73–95 | real index lines from both runs |
| native, hard-squeezed | ~200 | 12-topic run (2,200 chars / 11 entries) |
| native, realistic detail | ~604 | 3-fact run (1,813 chars / 3 entries) |

| against native at... | native entries | dynamic entries | ratio |
|---|---|---|---|
| hardest squeeze (200/entry) | 11 | 30 | **2.7x** |
| realistic detail (604/entry) | 3.6 | 30 | **8.3x** |

**Cite as "2.7x–8.3x, typically ~8x."** 2.7x is the adversarial floor — native
compressed to near-gibberish. 8.3x is what happened when both held the same facts
at real detail.

## 3. What these numbers do NOT say

- **"30 entries" is arithmetic, not demonstrated.** It is per-line cost times
  budget. Dynamic memory's real ceiling is untested; past roughly 20 index lines
  keyword collisions may begin costing retrieval precision.
- **The 6.4x is not free.** native holds complete facts usable with no I/O;
  dynamic holds keywords requiring a file read. If retrieval quality were worse,
  the compression would be deferral of work rather than a gain.
  **The measured tie in retrieval quality is what makes the trade legitimate** —
  5–20 keywords route to the same answer as the full text, at one sixth of the
  resident cost. That is the whole claim.

## 4. The best possible outcome is a tie

Worth stating explicitly, because it frames every future result: dynamic memory
**cannot** beat native on answer quality for content that fits resident.
The full text is the upper bound; a keyword index can only aim to match it.

So a tie is success, and the interesting measurements are always the second-order
ones: resident cost, entry capacity, and what happens past the cap.
