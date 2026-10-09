"""The loop, end to end, with a scripted offline model — no key, no network.

These tests are the demo's contract: if they pass, then when the model behaves in a given
way the receipts that come out are the receipts we say they are.
"""

import pytest

from receipts.agent import Agent, _parse_claims, _safe_eval, fallback_claims
from receipts.llm import MockClient, Reply, ToolCall
from receipts.receipts import CONTRADICTED, UNVERIFIED, VERIFIED
from receipts.store import DISPUTED, Store


@pytest.fixture()
def store():
    s = Store(":memory:")
    yield s
    s.close()


def tool_reply(name: str, **args) -> Reply:
    return Reply(text="", tool_calls=[ToolCall(id="c1", name=name, arguments=args)])


def test_no_evidence_yields_an_unverified_claim(store):
    client = MockClient([Reply(text="I don't know which district you live in.")])
    agent = Agent(client, store, extractor=lambda text, ledger: [{"text": text, "evidence": []}])
    turn = agent.ask("which district do I live in?")

    assert turn.steps == 1
    assert turn.answer.counts()[UNVERIFIED] == 1
    assert turn.answer.overclaim_rate() == 1.0


def test_recall_backed_claim_is_verified_and_points_at_the_fact(store):
    fact, _ = store.add_fact("Robin lives in Porto", source_kind="user_statement",
                             source_ref="chat", source_excerpt="我住在波尔图")
    client = MockClient([
        tool_reply("recall", query="where does Robin live"),
        Reply(text="You live in Porto."),
    ])
    agent = Agent(client, store,
                  extractor=lambda text, ledger: [{"text": text, "evidence": list(ledger)}])
    turn = agent.ask("where do I live?")

    assert turn.steps == 2
    assert turn.tool_runs[0].name == "recall"
    assert turn.tool_runs[0].receipt.kind == "fact"
    assert turn.tool_runs[0].receipt.status == VERIFIED
    assert turn.answer.claims[0].status == VERIFIED
    assert fact.id in turn.tool_runs[0].result


def test_a_contradiction_is_reported_and_nothing_is_overwritten(store):
    old, _ = store.add_fact("Robin lives in Porto", source_kind="user_statement")
    client = MockClient([
        tool_reply("remember", text="Robin lives in Berlin", excerpt="我搬到北京了"),
        Reply(text="You've told me two different things."),
    ])
    agent = Agent(client, store)
    # the batched judge is what decides; stub it so the test stays deterministic
    agent._judge_batch = lambda candidates, incoming: [c.id for c in candidates][:1]
    turn = agent.ask("I moved to Berlin")

    run = turn.tool_runs[0]
    assert '"outcome": "conflict"' in run.result
    # rule R2, end to end: the earlier fact is still readable, and it was not overwritten
    assert store.get(old.id).text == "Robin lives in Porto"
    assert store.get(old.id).status == DISPUTED
    assert len(store.conflicts()) == 1
    # and the receipt records what was compared, not merely that something happened
    assert "compared 1 existing fact" in run.receipt.note


def test_the_recency_window_is_what_catches_unrelated_wording(store):
    """A paraphrase shares no words with the stored fact — the pool must still contain it,
    or the judge never gets to see the pair. (The first version of this test used
    'Robin lives in Berlin', which shares ann/lives/in with the stored fact and so never
    exercised the recency window at all.)"""
    store.add_fact("Robin lives in Porto", source_kind="user_statement")
    seen = {}

    def batch(candidates, incoming):
        seen["texts"] = [c.text for c in candidates]
        return []

    store.add_fact("User relocated to the capital.", source_kind="user_statement",
                   recent=20, batch_judge=batch)
    assert store.last_check["lexical"] == 0, "this test is only meaningful with no lexical hit"
    assert "Robin lives in Porto" in seen["texts"]
    assert store.last_check["recent"] == 1
    assert store.last_check["checker"] == "model_batch"


def test_a_failed_computation_cannot_back_a_number(store):
    client = MockClient([
        tool_reply("compute", expression="__import__('os').system('echo hi')"),
        Reply(text="The answer is 42."),
    ])
    agent = Agent(client, store, extractor=lambda text, ledger: [{"text": text, "evidence": list(ledger)}])
    turn = agent.ask("compute something")

    receipt = turn.tool_runs[0].receipt
    assert "refused" in str(receipt.evidence.get("stdout_excerpt", "")) or \
           "refused" in turn.tool_runs[0].result
    assert receipt.status == CONTRADICTED
    assert turn.answer.claims[0].status == CONTRADICTED


def test_arithmetic_receipt_is_recheckable(store):
    client = MockClient([tool_reply("compute", expression="1234 / 7"), Reply(text="about 176.3")])
    agent = Agent(client, store, extractor=lambda text, ledger: [{"text": text, "evidence": list(ledger)}])
    turn = agent.ask("1234 over 7?")

    receipt = turn.tool_runs[0].receipt
    assert receipt.kind == "computation"
    assert receipt.evidence["result"] == pytest.approx(176.2857, rel=1e-3)
    assert receipt.verify_command == 'python -c "print(1234 / 7)"'


def test_reading_outside_the_note_root_is_refused(tmp_path, store):
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("do not read me\n", encoding="utf-8")
    client = MockClient([tool_reply("read_note", path=str(outside)), Reply(text="I could not read it.")])
    agent = Agent(client, store, note_root=str(tmp_path))
    turn = agent.ask("read that file")

    assert "outside the note root" in turn.tool_runs[0].result
    assert turn.tool_runs[0].receipt.kind == "none"


def test_step_limit_is_stated_not_hidden(store):
    client = MockClient([tool_reply("recall", query="x"), tool_reply("recall", query="x")])
    agent = Agent(client, store, max_steps=2)
    turn = agent.ask("loop forever")

    assert "step limit" in turn.answer.text


def test_claim_parser_and_fallback():
    assert _parse_claims('sure! {"claims": [{"text": "a", "evidence": []}]} thanks')[0]["text"] == "a"
    assert _parse_claims("not json at all") == []
    # with nothing to check against, every sentence is unsupported — deliberately pessimistic
    assert len(fallback_claims("You live in Porto. You work on agents.")) == 2
    assert all(c["evidence"] == [] for c in fallback_claims("One. Two."))


def test_safe_eval_allows_arithmetic_only():
    assert _safe_eval("2 ** 10")[0] == 1024
    assert _safe_eval("__import__('os')")[1] == 1
    assert _safe_eval("open('x')")[1] == 1
