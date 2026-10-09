"""The receipt layer: four states, a re-check command on every receipt, and a counted miss."""

import pytest

from receipts.receipts import (
    CONTRADICTED,
    STALE,
    UNVERIFIED,
    VERIFIED,
    Answer,
    Claim,
    audit_lines,
    computation_receipt,
    fact_receipt,
    none_receipt,
    quote_receipt,
    tool_receipt,
)
from receipts.store import Store


@pytest.fixture()
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_claim_status_is_the_worst_of_its_receipts(store):
    f, _ = store.add_fact("Robin lives in Porto", source_kind="user_statement")
    c = Claim("you live in Porto", [fact_receipt(store, f.id), none_receipt("no idea about the district")])
    assert c.status == UNVERIFIED          # one good receipt does not launder a bad one
    assert c.receipt.status == UNVERIFIED  # and the deciding receipt is exposed


def test_claim_without_receipts_is_unverified():
    assert Claim("you probably like tea").status == UNVERIFIED


def test_receipt_for_a_fact_that_no_longer_exists_is_contradicted(store):
    r = fact_receipt(store, "f_deadbeef00")
    assert r.status == CONTRADICTED
    assert r.verify_command is None


def test_receipt_for_a_retracted_fact_is_contradicted_not_verified(store):
    f, _ = store.add_fact("Robin's plan is to move abroad", source_kind="inference")
    store.retract(f.id, reason="she said otherwise")
    r = fact_receipt(store, f.id)
    assert r.status == CONTRADICTED


def test_old_fact_reads_as_stale_never_as_verified(store):
    f, _ = store.add_fact("Robin uses Windows", source_kind="user_statement")
    r = fact_receipt(store, f.id, freshness_days=-1)   # freshness window in the past
    assert r.status == STALE


def test_tool_receipt_contradicts_a_success_claim_that_failed():
    ok = tool_receipt("python -c 'print(1)'", 0, "1\n")
    bad = tool_receipt("python -c 'boom'", 1, "Traceback...", claim_says_success=True)
    honest = tool_receipt("python -c 'boom'", 1, "Traceback...", claim_says_success=False)
    assert ok.status == VERIFIED
    assert bad.status == CONTRADICTED
    assert honest.status == VERIFIED      # claiming a failure, with the failure as evidence


def test_every_kind_of_receipt_can_be_re_checked_by_the_reader(tmp_path):
    src = tmp_path / "notes.md"
    src.write_text("the deadline is October 30\n", encoding="utf-8")
    receipts = [
        tool_receipt("echo hi", 0, "hi"),
        computation_receipt("2 ** 10", 1024),
        quote_receipt(str(src), "the deadline is October 30"),
    ]
    for r in receipts:
        assert r.verify_command, f"{r.kind} receipt has no way for a reader to re-check it"


def test_the_explicit_no_evidence_state_is_counted_not_hidden():
    a = Answer(
        question="what district do I live in?",
        text="I'm not sure — I only know the city.",
        claims=[
            Claim("you live in Porto", [none_receipt("no source for the district")]),
        ],
    )
    c = a.counts()
    assert c[UNVERIFIED] == 1 and c[VERIFIED] == 0
    assert a.overclaim_rate() == 1.0


def test_overclaim_rate_and_audit_list(store):
    f, _ = store.add_fact("the report has 40 tables", source_kind="tool_output")
    a = Answer(
        question="how many tables?",
        text="40 tables, and I saved the file.",
        claims=[
            Claim("the report has 40 tables", [fact_receipt(store, f.id)]),
            Claim("I saved the file", [tool_receipt("cp a b", 1, "denied", claim_says_success=True)]),
        ],
    )
    assert a.counts()[VERIFIED] == 1
    assert a.counts()[CONTRADICTED] == 1
    assert abs(a.overclaim_rate() - 0.5) < 1e-9

    lines = audit_lines(a)
    assert len(lines) == 1 and "I saved the file" in lines[0]
