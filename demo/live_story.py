"""The same three scenes as `offline_story.py`, but against a real model.

Nothing here is scripted: the tool calls, the contradiction judgement and the claim
extraction are all whatever the model actually produces. Point it at any OpenAI-compatible
endpoint (Nebius Token Factory in the submission; anything else works for development):

    RECEIPTS_BASE_URL=https://api.tokenfactory.us-central1.nebius.com/v1 \\
    NEBIUS_API_KEY=... RECEIPTS_MODEL_ULTRA=nvidia/Nemotron-3-Ultra-550b-a55b \\
    python demo/live_story.py

Exit code is 0 if the run completed; it does not assert model quality (that is what
`eval/` is for). What it prints is the evidence: which claims got receipts, and which did not.
"""

import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from receipts.agent import Agent  # noqa: E402
from receipts.llm import NebiusClient  # noqa: E402
from receipts.store import Store  # noqa: E402


def banner(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    client = NebiusClient()
    if not client.api_key:
        print("no API key — set NEBIUS_API_KEY (see .env.example)", file=sys.stderr)
        return 2

    print(f"endpoint : {client.base_url}")
    print(f"model    : {client.model_ultra}")

    store = Store(":memory:")
    store.add_fact(
        "Robin lives in Porto",
        source_kind="user_statement",
        source_ref="chat 2026-09-12",
        source_excerpt="我住在波尔图，Ribeira 那边",
    )
    agent = Agent(client, store)  # real extraction prompt, real judge

    banner("SCENE 1 — an answer it can back")
    turn = agent.ask("where do I live?")
    print(turn.answer.render())
    print(f"\n[tool calls this turn: {[r.name for r in turn.tool_runs]}]")

    banner("SCENE 2 — something that contradicts memory")
    turn2 = agent.ask("I moved to Berlin last month — 我上个月搬到北京了")
    print(turn2.answer.render())
    print(f"\n[open conflicts in the store: {len(store.conflicts())}]")
    for a, b in store.conflicts():
        print(f"  ! {a.text!r}  vs  {b.text!r}")

    banner("SCENE 3 — something it cannot back")
    turn3 = agent.ask("which district of Porto do I live in, and what's my landlord's name?")
    print(turn3.answer.render())

    banner("SUMMARY")
    total = sum(len(t.answer.claims) for t in (turn, turn2, turn3))
    bad = sum(t.answer.counts()["unverified"] + t.answer.counts()["contradicted"]
              + t.answer.counts()["stale"] for t in (turn, turn2, turn3))
    print(f"claims across 3 turns : {total}")
    print(f"not properly backed   : {bad}")
    print(f"overclaim rate        : {bad / total:.2%}" if total else "no claims extracted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
