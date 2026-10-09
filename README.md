# Receipts — a personal AI that shows its work

> **Show me the receipts.**
> An always-on personal assistant whose memory and claims are *auditable*: every durable
> fact carries its source, every claim in an answer carries evidence you can re-run
> yourself, and *"I don't know"* is a first-class answer instead of a confident guess.

Built for the **Nebius × NVIDIA Global AI Hackathon** (Personal AI track), running on
**NVIDIA Nemotron** models served by **Nebius Token Factory**.

---

## Why this exists

Every personal assistant has memory now. Almost none of them can answer the two questions
that actually decide whether you should trust one:

1. **"Why do you believe that?"** — Where did this fact come from, when, and what exactly
   did I say?
2. **"What are you telling me that you can't back up?"** — A self-audit over everything it has
   ever claimed.

Current assistants fail these in three specific, reproducible ways:

| Failure | What it looks like | What Receipts does |
|---|---|---|
| **Silent overwrite** | You change your mind / move house; the new fact replaces the old one with no trace | A contradicting fact raises a **conflict**; nothing is overwritten until you decide |
| **Confident guessing** | "You usually prefer X" — with no source, invented or stale | Every claim carries a **receipt**; no receipt ⇒ it says **unverified** |
| **Unknown collapsing into false** | A fact that was never re-checked reads the same as one that was disproved | `unknown` / `unverified` / **contradicted** are three separate states |

## What it does

- **Provenance on every fact** — source kind, source ref, verbatim excerpt, timestamp.
- **Retraction is an operation, not a deletion** — append-only event log; the history stays.
- **Conflict detection** — new evidence that contradicts an existing fact stops and asks.
- **Receipts on claims** — each claim in an answer is one of: `fact` (points at a stored
  fact) · `tool` (a command that ran, with its output hash) · `computation` (an expression
  and its result) · `quote` (a source and excerpt) · `none`.
- **`receipts audit`** — dumps everything asserted without backing, with a re-check command
  for each.
- **A measured overclaim rate** — the repo ships an evaluation harness that runs a task set
  with and without the receipt layer and reports the difference with confidence intervals.
  (Our own numbers, including the embarrassing ones.)

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env          # then put your Nebius Token Factory key in it

python -m receipts.cli chat   # interactive
python -m receipts.cli audit  # what can't it back up?
python -m receipts.cli eval   # overclaim rate, with and without receipts
```

## Architecture

```
src/receipts/
  store.py      memory: facts + provenance + retraction + conflicts (SQLite, append-only log)
  receipts.py   the claim/receipt model and its four states
  llm.py        Nebius Token Factory client (OpenAI-compatible) + an offline mock
  agent.py      the tool loop (remember / recall / verify / retract / conflict)
  audit.py      self-audit: what did I claim that I can't back?
  cli.py        entry point
demo/           one-page web UI: chat on the left, the receipts of the last answer on the right
eval/           the overclaim-rate measurement (with/without the receipt layer)
```

## Models

| Role | Model | Why |
|---|---|---|
| Reasoning / hard calls | `nvidia/Nemotron-3-Ultra-550b-a55b` | 550B MoE (55B active), 1M ctx, strong tool calling |
| Always-on execution | `nvidia/Nemotron-3_5-Lightning` | 30B MoE (3B active) — built as the execution layer for long-running agents |

Both served by Nebius Token Factory (`https://api.tokenfactory.us-central1.nebius.com/v1/`).

## Honest limitations

- Conflict detection is heuristic + model-judged, not a theorem prover.
- "Verified" means *re-checked at this time by this method* — not *true*.
- The overclaim-rate experiment is small-n by design; the repo reports intervals, not verdicts.

## License

MIT — see `LICENSE`.
