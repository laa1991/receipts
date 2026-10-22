# Plan, and what actually happened

This document started as a 21-day plan to submit to the **Nebius × NVIDIA Global AI
Hackathon** (deadline 2026-10-30 10:00 PDT). **The submission did not happen** — not because
the work was unfinished, but because the platform could not be provisioned for us.

The plan is kept as originally written, with the outcome of each item marked next to it. A
stale plan that still says "submit on Friday" is worse than no plan, so the states below are
the true ones.

## Why it stopped

```
2026-10-15  support ticket CLOUDSUPPORT-1199475 (opened 19:18, answered 19:37, closed):
             "China is not among the countries supported on Nebius."
```

- Nebius's billing/country-of-residence list has no **China**, so a billing account cannot be
  created — and per Nebius's own documentation a promo code can only be applied **after**
  payment details (card + a $25 minimum payment) are in place.
- The hackathon rules require the project to run on **Nebius Token Factory or Nebius AI
  Cloud**, so without an account the submission requirement cannot be met.
- The organisers' FAQ describes this as an account-provisioning gap on Nebius's side rather
  than an eligibility rule, and says there is no Devpost-side workaround. Both official
  channels were tried: the Discord server (6 days, no reply) and support (definitive "no",
  in 19 minutes).

Everything else — memory, receipts, the app, the experiment — is independent of which
endpoint serves the model, so it was built and measured against another OpenAI-compatible
endpoint. `RECEIPTS_BASE_URL` is the only line that would change.

## The plan, with outcomes

| # | Item | Original owner | Outcome |
|---|---|---|---|
| 1 | Join hackathon on Devpost | human | **done** |
| 2 | Claim the $25 Token Factory credits | human | promo codes received (`$25` × 2) — **never redeemable**: no billing account |
| 3 | Join the Nebius Builders Program | human | **accepted** — same dead end as #2 |
| 4 | Create an API key, write it into `.env` | human | **never** — blocked by the country list |
| 5 | Memory store (provenance / retraction / conflicts) | agent | **done** |
| 6 | Receipt model + four states | agent | **done** |
| 7 | Agent loop with tools | agent | **done** |
| 8 | Offline story demo | agent | **done** |
| 9 | First real call (`receipts smoke`) | agent | **done against a different endpoint**, never against Token Factory |
| 10 | Claim-extraction prompt tuned on the real model | agent | **done** — and it exposed a systematic ruler flaw (see `experiment.md`) |
| 11 | Web UI: chat + receipts panel | agent | **done** (`demo/app.py`, screenshot in the README) |
| 12 | Self-audit screen ("what can't you back?") | agent | **done** |
| 13 | Overclaim-rate experiment | agent | **done** — five runs; result is "suggestive, not established" |
| 14 | Demo video (≤ 3 min) | agent script + human records | **not recorded** — script ready in `docs/video-script.md` |
| 15 | README, license, `.env.example` | agent | **done** |
| 16 | Submit + write the Token Factory feedback | both | **did not happen** (#4) |
| 17 | Publish the repo publicly | human | **done** — this repository |

## What would be needed to finish the submission

Three things, in order of hardness:

1. **A Nebius account in a supported country** — the only real blocker, and not something the
   project can work around.
2. **A 3-minute recording** — the script exists (`docs/video-script.md`); it needs one live
   session and a screen recorder.
3. **The feedback section** the rules ask for — writable now from what we experienced, and
   the honest version of it would say: onboarding was smooth, the promo flow and the billing
   flow do not meet in the middle for some countries, and the model API itself (OpenAI
   compatible, 30+ open models) looked like the least interesting part of the setup, which is
   a compliment.

## The three scenes the video must show

1. **An answer with a receipt** — ask about something stored; the answer shows the fact, its
   source, when it was stated, and a command the viewer can run to re-check it.
2. **A contradiction** — tell it something that conflicts. It must *not* overwrite: both
   versions stay, the question comes back to the human, and the loser is marked, not deleted.
3. **An honest "I don't know"** — ask something it has no source for, then run the self-audit
   and show that the unsupported assertion is counted, not hidden.

## The experiment

Run the same task set in two arms — with the receipt discipline and without — scoring both
with **one shared ruler**, and report the overclaim rate with intervals. Done, five times
over, including two runs that had to be thrown away. The write-up is `docs/experiment.md`;
the short version is that the deterministic guarantees hold, while the behavioural effect is
suggestive and not established at this sample size.

## Rules we hold ourselves to

- Every number in the README comes from a command in this repo.
- `unknown` never collapses into `false`.
- Nothing is published, submitted, or uploaded without the owner's explicit word.
