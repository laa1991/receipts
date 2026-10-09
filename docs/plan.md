# Plan — 21 days to submission

Deadline: **2026-10-30 10:00 PDT = 2026-10-31 01:00 Berlin** (confirmed on the official page).
Submission needs: working project · public repo (license visible at top) · demo URL · ≤3-min public
YouTube video · feedback on Token Factory / AI Cloud / NVIDIA tooling.

## Status board

| # | Item | Owner | State |
|---|---|---|---|
| 1 | Join hackathon on Devpost | Robin | — |
| 2 | Claim $25 Token Factory credits (`NEBIUS-DEVPOST-GLOBAL26`) | Robin | — |
| 3 | Join Nebius Builders Program (+$25) | Robin | — |
| 4 | Create API key, write it into `.env` | Robin | — |
| 5 | Memory store (provenance / retraction / conflicts) | D | **done** (19 tests) |
| 6 | Receipt model + four states | D | **done** |
| 7 | Agent loop with tools | D | **done** (9 tests) |
| 8 | Offline story demo | D | **done** |
| 9 | First real call (`receipts smoke`) | D | blocked on #4 |
| 10 | Claim-extraction prompt tuned on the real model | D | next after #9 |
| 11 | Web UI: chat + receipts panel | D | todo |
| 12 | Self-audit screen ("what can't you back?") | D | todo |
| 13 | Overclaim-rate experiment (with/without receipts, n≥30, CI) | D | todo |
| 14 | Demo video (≤3 min, public YouTube) | D script + Robin records | todo |
| 15 | README polish, license check, `.env.example` | D | partly done |
| 16 | Submit + write the Token Factory feedback | Robin + D | todo |
| 17 | Publish repo to GitHub (public) | Robin | todo — irreversible |

## The three scenes the video must show

1. **An answer with a receipt** — ask about something stored; the answer shows the fact, its
   source, when it was stated, and a command the viewer can run to re-check it.
2. **A contradiction** — tell it something that conflicts. It must *not* overwrite: both
   versions stay, the question comes back to the human, and the loser is marked, not deleted.
3. **An honest "I don't know"** — ask something it has no source for, then run the self-audit
   and show that unsupported assertion counted, not hidden.

## The experiment (this is what makes it more than a demo)

Run the same task set twice — with the receipt layer and with it disabled — and report the
**overclaim rate** in both arms with confidence intervals. Failure mode to watch: the judge
(and our own extractor) can be lenient; any leniency must be reported, not smoothed over.

## Rules we hold ourselves to

- Every number in the README comes from a command in this repo.
- `unknown` never collapses into `false`.
- Nothing is published, submitted, or uploaded without Robin's explicit word.
