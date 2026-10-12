# Experiment: does the receipt discipline reduce unsupported claims?

**Short answer: we could not detect an effect, and we can say how much data it would take.**

This document reports the four runs we did, including the two that we later discarded, because
the discarded ones are the reason the last two are worth anything.

## Design

Same model, same memory store, same tools, same task set. The **only** difference between the
two arms is the system prompt:

| arm | prompt |
|---|---|
| `plain` | a plain helpful-assistant prompt; the tools are available but nothing demands evidence |
| `receipts` | the assistant must back every factual assertion with a tool result, and must say so when it cannot |

One **shared ruler** scores both arms: the same claim-extraction pass maps each assertion in
the answer onto the evidence gathered during that turn. A different ruler per arm would make
the comparison meaningless.

Task set: 10 tasks over a seeded store of 3 facts.
- 3 *answerable* (a stored fact covers it)
- 4 *unanswerable* (nothing in memory — the interesting case: invent, or say "I don't know"?)
- 2 *compute* (an expression must be evaluated)
- 1 *contradiction* (the new statement conflicts with a stored one)

Primary metric: **share of extracted assertions with no valid receipt** (a "claim" that is
`unverified`, `stale` or `contradicted`).

## Runs

| run | ruler | samples/task | plain | receipts | difference | paired sign test |
|---|---|---|---|---|---|---|
| 1 | note-only | 1 | 50% (14/28) | 26% (7/27) | −24 | — |
| 2 | note-only | 1 | 29% (7/24) | 39% (11/28) | +10 | — |
| 3 | payload | 3 | 16% (12/77) | 23% (19/84) | −7 | p = 1.000 |
| 4 | payload | 3 | 26% (21/80) | 20% (16/79) | +6 | p = 0.727 |

### What we got wrong first

Runs 1 and 2 used a ruler that was shown only the **one-line summary** of each receipt
("`Robin lives in Porto` (from user_statement)"), not the payload. An answer sentence like
*"you told me on 2026-09-12 that you live in Ribeira"* is **supported** by that receipt — the
date and the district are in its `source_ref` and `excerpt` — but the ruler could not see them
and scored the sentence unbacked. That is a **systematic** error, and it inflated both arms.

Two things followed:

1. The ruler now receives the receipt **payload** (`evidence` JSON, with excerpts, source refs
   and command output), and the prompt tells it that a date, a quote or a number inside the
   payload counts as support.
2. We checked the ruler's own noise directly (`eval/ruler_noise.py`): one fixed answer, scored
   5 times, gave an **identical** unbacked count every time. My hypothesis — "the ruler is the
   noisy part" — was wrong, and measuring it was cheaper than arguing about it.

### Why runs 3 and 4 still decide nothing

They are the **same configuration**, and their difference still flips sign (−7 → +6). The
between-run spread is as large as any effect we might be looking for. With 10 tasks the
study is simply **underpowered**: the point estimates are noise, which is what the paired
test says (p = 1.000, p = 0.727).

Rough sizing, from the observed spread (≈6.5 points between runs of this size): detecting a
10-point difference with 80% power would need on the order of **3× the data** — more tasks
and more samples per task. We did not run that, so we do not claim the effect.

Where a real effect would most likely live, if there is one: the **unanswerable** row
(run 4: plain 46% → receipts 20%; run 1, with the broken ruler: 60% → 0%). It is the row the
mechanism is designed for, and it is the row where the arms diverge in the expected direction
in every run. It is also, at n=4 tasks, exactly the kind of number that should not be quoted
as a result.

## The endpoint that does not go through the model

The metric above is scored by a model, which is why it is noisy. So we added a **deterministic**
endpoint for the contradiction task: after the turn, does the memory store hold *both*
versions (`store.conflicts()` non-empty), and did the answer hand the decision back to the user?

```
plain     n=3   both versions kept: 3/3   handed back: 3/3
receipts  n=3   both versions kept: 3/3   handed back: 3/3
```

**No difference — and that is the interesting part.** The two arms are identical here because
the guarantee lives in the *tool*, not in the prompt: `remember` compares the incoming fact
against the existing pool and raises a conflict instead of overwriting, whatever the model
was asked to do. A property that holds even when the model is not trying is worth more than a
behaviour that only shows up when it is.

## What we take from it

- **The auditable layer is deterministic and demonstrable**: provenance on every fact,
  conflicts kept instead of overwritten, an explicit "no evidence" state, and a command a
  reader can run to re-check each receipt.
- **The behavioural claim is not established here.** "Being asked to show receipts makes a
  model overclaim less" is a plausible hypothesis that our data does not support. Anyone
  quoting a number from this repo should quote one of the tables above, with its n.
- The reusable lesson is the measurement one: *check the ruler before you check the arms, and
  then run the same configuration twice before believing a difference.*

## Reproduce

```bash
RECEIPTS_BASE_URL=... NEBIUS_API_KEY=... RECEIPTS_MODEL_ULTRA=... \
  python eval/overclaim.py --n 10 --samples 3 --out eval/overclaim-run5.json
python eval/ruler_noise.py --k 5
```

Results are written as JSON (`eval/overclaim-run*.json`, `eval/ruler-noise.json`) **before**
any human-readable summary is printed — a lesson learned the hard way: an encoding error in
the printing step once destroyed a finished run's artifact.
