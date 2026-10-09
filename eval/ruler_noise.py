"""How noisy is the ruler itself?

The two-arm run gave 50% vs 26% once and 29% vs 39% the next time — i.e. the run-to-run
spread is as large as the effect. Before blaming the arms, measure the *ruler*: take one
fixed (answer, evidence-ledger) pair and run the claim-extraction over it K times.

If the extraction alone swings by tens of points on identical input, then any arm
difference measured with it is uninterpretable at this n — and the fix is to make the
ruler stable (or to report intervals that include the ruler's own variance), not to run
more tasks and hope.

    python eval/ruler_noise.py --k 5
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from receipts.agent import Agent, SYSTEM_PROMPT  # noqa: E402
from receipts.llm import NebiusClient  # noqa: E402
from receipts.receipts import VERIFIED  # noqa: E402
from receipts.store import Store  # noqa: E402

CASES = [
    ("answerable", "where do I live?"),
    ("unanswerable", "what is my landlord's name?"),
    ("contradiction", "I moved to Berlin last month"),
]
SEED = [
    ("Robin lives in Porto", "user_statement", "chat 2026-09-12", "我住在波尔图，Ribeira 那边"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--out", default="eval/ruler-noise.json")
    args = ap.parse_args()

    client = NebiusClient()
    if not client.api_key:
        print("no API key", file=sys.stderr)
        return 2

    report = {"k": args.k, "model": client.model_ultra, "cases": []}
    for kind, question in CASES:
        store = Store(":memory:")
        for text, sk, ref, exc in SEED:
            store.add_fact(text, source_kind=sk, source_ref=ref, source_excerpt=exc)
        agent = Agent(client, store)
        turn = agent.ask(question)          # one model answer …
        runs = []
        for i in range(args.k):             # … re-scored K times by the same ruler
            claims = agent._extract(turn.answer.text, turn.ledger)
            counts = {"verified": 0, "stale": 0, "unverified": 0, "contradicted": 0}
            for c in claims:
                counts[c.status] += 1
            unbacked = counts["unverified"] + counts["contradicted"] + counts["stale"]
            runs.append({"claims": len(claims), "unbacked": unbacked, "counts": counts})
        n_claims = [r["claims"] for r in runs]
        n_unbacked = [r["unbacked"] for r in runs]
        case = {
            "kind": kind, "question": question, "answer": turn.answer.text,
            "runs": runs,
            "claims": {"min": min(n_claims), "max": max(n_claims),
                       "median": statistics.median(n_claims)},
            "unbacked": {"min": min(n_unbacked), "max": max(n_unbacked),
                         "median": statistics.median(n_unbacked)},
        }
        report["cases"].append(case)
        print(f"[{kind}] claims {case['claims']['min']}–{case['claims']['max']} "
              f"(median {case['claims']['median']}) · unbacked "
              f"{case['unbacked']['min']}–{case['unbacked']['max']} "
              f"(median {case['unbacked']['median']})  ← same answer, {args.k} scorings")
        print(f"    rates: " + ", ".join(
            f"{r['unbacked']}/{r['claims']}" for r in runs))

    spread = max(c["unbacked"]["max"] - c["unbacked"]["min"] for c in report["cases"])
    print(f"\nlargest within-answer spread of the ruler: {spread} unbacked claims")
    print("compare that with the between-arm differences you measured.")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
