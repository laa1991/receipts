# Demo video script (≤ 3:00, public YouTube)

Requirements this has to satisfy (from the official rules): a public video of **3 minutes or
shorter**, with audio, showing the project working, covering **how we used Nebius Token
Factory and an NVIDIA open-source model**, plus the feedback section at the end.

Record with the app already running and the store seeded. Screen capture of the browser; no
slides except where noted. Speak at a normal pace — the timing below is generous, and it is
better to cut a sentence than to rush one.

---

## 0:00 – 0:15 · The problem

**On screen:** the app, empty chat, empty receipts panel.

> "Every personal assistant has memory now. Almost none of them can answer two questions:
> *why do you believe that?* — and *what are you telling me that you can't back up?*
> This is an assistant built so that both questions have an answer you can check yourself."

## 0:15 – 0:45 · An answer that carries a receipt

**Do:** type `where do I live?` · run it.

**On screen:** the answer appears; on the right, the receipt panel: the stored fact, its
source (`user_statement`, chat 2026-09-12), the **verbatim excerpt**, and a re-check command.

> "It answers — and every claim is attached to the evidence behind it. Not a confidence
> score: the source, the date, and the exact words it came from. And this line at the bottom
> is a command I can run to re-check it myself."

**Do:** point at the claim statuses (`verified` / `unverified`), then press **Self-audit**.

> "The self-audit asks the harder question: what has it said that it cannot back? Right now,
> nothing — every claim carries a receipt."

## 0:45 – 1:30 · A contradiction is not an overwrite

**Do:** type `I moved to Berlin last month` · run it.

**On screen:** the answer returns both versions and asks which one holds; the receipts panel
shows the conflict; the store panel lists the two facts as *awaiting your decision*.

> "I told it something that conflicts with what it already knew. It did **not** overwrite.
> Both versions are still here — the old one was marked, not deleted — and it hands the
> decision back to me. This is the part most memory systems get wrong: the new fact silently
> replaces the old one, and you never find out."

**Do:** resolve the conflict in the UI, then show that the losing fact is still in the record.

> "I decide. The other version is superseded — still in the history, with the reason."

## 1:30 – 2:05 · The honest "I don't know"

**Do:** type `what is my landlord's name?` · run it.

**On screen:** the answer says it doesn't know; the audit counts it as *unverified* rather
than hiding it.

> "Here's the case that matters most. It doesn't know — and it says so. `unverified` is a
> state in the ledger, not a footnote: it gets counted, and it shows up in the audit. Nothing
> collapses 'I never checked' into 'false', and nothing collapses it into 'true' either."

## 2:05 – 2:40 · What we measured (and what we refused to claim)

**On screen:** the table from `docs/experiment.md`.

> "We ran a two-arm experiment: same model, same memory, same tools — the only difference is
> whether the assistant is required to show evidence. Four runs. The first two had a broken
> ruler; after fixing it, two runs of the *same* configuration gave −7 and +6 points. So we
> don't claim an effect: at this sample size we can't detect one, and we can say roughly how
> much data it would take.
>
> But one endpoint doesn't go through a model at all — did the store keep both versions, and
> ask? Both arms: three out of three. That guarantee lives in the tool, not in the prompt.
> It holds even when the model isn't trying."

## 2:40 – 3:00 · How it runs on Nebius

**On screen:** the model name and endpoint in the header; the repo README.

> "The assistant runs on **NVIDIA Nemotron** served by **Nebius Token Factory** — Nemotron 3
> Ultra for the hard calls, Nemotron 3.5 Lightning, which NVIDIA built as the execution layer
> for long-running agents, for the everyday ones. The client is OpenAI-compatible: change the
> base URL and it ships. Code, receipts and the experiment are in the repo — including the
> runs that didn't work."

---

## Feedback section (record separately, keep ~20 s)

Name the tools concretely and say what worked and what did not — the rules ask for this
explicitly and vague praise counts for nothing:

- **Token Factory / onboarding**: what was smooth, what blocked us (be specific about the
  billing country list, since that is our real experience).
- **Nemotron**: which model we used for what, and where it surprised us.
- **Would we build on it again, and why.**

## Before recording — checklist

- [ ] `python -m receipts.cli smoke` returns a real completion (the header must show a live
      model, not `mock`).
- [ ] Fresh database, so the demo starts from the seeded facts.
- [ ] Browser at a readable zoom; close every other tab.
- [ ] The re-check command in the receipt panel actually runs when pasted into a terminal.
- [ ] Total length under 3:00 — time a rehearsal.
- [ ] Video is **public** on YouTube, audio present, title names the project.
