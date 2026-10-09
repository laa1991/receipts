"""The whole story, offline: no key, no network — only a scripted model.

Run:  python demo/offline_story.py

It walks the three scenes the demo video will use:
  1. a question it can answer *with* evidence,
  2. something the user says that contradicts memory (it must not overwrite),
  3. a question it cannot back (it must say so, and that must show up in the audit).
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles are GBK
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from receipts.agent import Agent                      # noqa: E402
from receipts.llm import MockClient, Reply, ToolCall  # noqa: E402
from receipts.store import Store                      # noqa: E402


def tool_reply(name, **args):
    return Reply(text="", tool_calls=[ToolCall(id="c1", name=name, arguments=args)])


def banner(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    store = Store(":memory:")
    store.add_fact(
        "Robin lives in Porto",
        source_kind="user_statement",
        source_ref="chat 2026-09-12",
        source_excerpt="我住在波尔图，Ribeira 那边",
    )
    store.add_fact(
        "Robin is learning to sail",
        source_kind="user_statement",
        source_ref="chat 2026-09-20",
        source_excerpt="我刚开始学帆船",
    )

    # --- scene 1: an answer that carries a receipt ------------------------------------
    banner("SCENE 1 — an assertion the assistant can back")
    client = MockClient([
        tool_reply("recall", query="where does Robin live"),
        Reply(text="You live in Porto (you told me on 2026-09-12)."),
        Reply(text='{"claims":[{"text":"You live in Porto.","evidence":["e1"]}]}'),
    ])
    agent = Agent(client, store, extractor=None)
    # keep the extraction deterministic in the offline story
    agent._extractor = lambda text, ledger: [{"text": text, "evidence": list(ledger)}]
    turn = agent.ask("where do I live?")
    print(turn.answer.render())

    # --- scene 2: something new that contradicts what is stored ------------------------
    banner("SCENE 2 — new information contradicts memory (nothing may be overwritten)")
    client = MockClient([
        tool_reply("remember", text="Robin lives in Berlin",
                   excerpt="我上个月搬到北京了", source_ref="chat 2026-10-09"),
        Reply(text="contradict"),  # the judge call
        Reply(text="I have two conflicting versions: Porto (2026-09-12) and Berlin "
                   "(2026-10-09). I have not overwritten either — which one holds?"),
    ])
    judge_agent = Agent(client, store, model_judge=True)
    judge_agent._extractor = lambda text, ledger: [{"text": text, "evidence": list(ledger)}]
    turn = judge_agent.ask("I moved to Berlin last month")
    print(turn.answer.render())
    print("\n  memory store says:")
    for a, b in store.conflicts():
        print(f"    ! {a.text!r}   vs   {b.text!r}")

    # --- scene 3: what it cannot back ---------------------------------------------------
    banner("SCENE 3 — a question it cannot back (the honest state must be visible)")
    client = MockClient([Reply(text="I don't know which district — you never told me.")])
    agent3 = Agent(client, store)
    agent3._extractor = lambda text, ledger: [{"text": text, "evidence": []}]
    turn = agent3.ask("which district of Porto do I live in?")
    print(turn.answer.render())

    # --- the self-audit -----------------------------------------------------------------
    banner("SELF-AUDIT — what did it assert that it cannot back?")
    print(f"open conflicts: {len(store.conflicts())}")
    print(f"live facts: {len(store.facts())}")
    print("\nprovenance of one fact:")
    fact = store.facts()[0]
    prov = store.provenance(fact.id)
    print(f"  fact      : {prov['fact']}")
    print(f"  stated    : {prov['stated']}")
    print(f"  source    : {prov['source']['kind']} / {prov['source']['ref']}")
    print(f"  excerpt   : {prov['source']['excerpt']}")
    print(f"  history   : {[e['kind'] for e in prov['history']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
