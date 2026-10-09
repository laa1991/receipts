"""The three rules of the memory store, each with a test that would fail if it broke."""

import pytest

from receipts.store import ACTIVE, DISPUTED, RETRACTED, SUPERSEDED, Store, overlap


@pytest.fixture()
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_fact_keeps_its_source(store):
    f, outcome = store.add_fact(
        "Robin lives in Porto",
        source_kind="user_statement",
        source_ref="wechat 2026-10-01 21:14",
        source_excerpt="我住在波尔图",
    )
    assert outcome == "added"
    assert f.source_kind == "user_statement"
    assert f.source_ref == "wechat 2026-10-01 21:14"
    assert f.source_excerpt == "我住在波尔图"
    assert f.status == ACTIVE

    prov = store.provenance(f.id)
    assert prov["source"]["excerpt"] == "我住在波尔图"
    assert [e["kind"] for e in prov["history"]] == ["fact.added"]


def test_empty_fact_is_refused(store):
    with pytest.raises(ValueError):
        store.add_fact("   ", source_kind="user_statement")


def test_unknown_source_kind_is_refused(store):
    with pytest.raises(ValueError):
        store.add_fact("something", source_kind="vibes")


def test_same_fact_is_not_stored_twice(store):
    text = "Robin prefers written summaries over meetings"
    first, out1 = store.add_fact(text, source_kind="user_statement")
    second, out2 = store.add_fact(text, source_kind="user_statement")
    assert out1 == "added" and out2 == "duplicate"
    assert first.id == second.id
    assert len(store.facts()) == 1


def test_contradiction_raises_a_conflict_instead_of_overwriting(store):
    old, _ = store.add_fact("Robin lives in Porto", source_kind="user_statement")

    def judge(existing: str, incoming: str) -> str:
        return "contradict" if "lives in" in existing and "lives in" in incoming else "unrelated"

    new, outcome = store.add_fact("Robin lives in Berlin", source_kind="user_statement", judge=judge)

    assert outcome == "conflict"
    # rule R2: the old fact is still on disk, still readable, and explicitly marked
    assert store.get(old.id).text == "Robin lives in Porto"
    assert store.get(old.id).status == DISPUTED
    assert store.get(new.id).status == DISPUTED
    assert len(store.conflicts()) == 1


def test_resolving_a_conflict_keeps_both_rows_and_the_reason(store):
    old, _ = store.add_fact("Robin lives in Porto", source_kind="user_statement")
    new, _ = store.add_fact("Robin lives in Berlin", source_kind="user_statement", judge=lambda a, b: "contradict")

    kept = store.resolve_conflict(keep=new.id, drop=old.id, reason="she moved in October")

    assert kept.status == ACTIVE
    loser = store.get(old.id)
    assert loser.status == SUPERSEDED
    assert loser.superseded_by == new.id          # nothing was deleted
    assert store.conflicts() == []
    kinds = [e["kind"] for e in store.events(old.id)]
    assert "fact.retracted" not in kinds and "fact.conflict_resolved" in kinds


def test_retraction_is_an_operation_not_a_deletion(store):
    f, _ = store.add_fact("Robin's phone is an Android", source_kind="user_statement")
    store.retract(f.id, reason="she switched")

    assert store.get(f.id).status == RETRACTED
    assert store.get(f.id).text == "Robin's phone is an Android"
    assert store.events(f.id)[-1]["kind"] == "fact.retracted"
    assert f.id not in [x.id for x in store.facts()]        # gone from the live set
    assert f.id in [x.id for x in store.facts(status=None)]  # still in the record


def test_unchecked_is_stale_not_false(store):
    f, _ = store.add_fact("Robin works at company X", source_kind="inference")
    assert f.is_fresh(30) is True                 # just created ⇒ not stale
    assert f.status == ACTIVE                     # and definitely not "false"
    store.verify(f.id, method="asked her again", ok=True)
    assert store.get(f.id).verified_at is not None


def test_search_reports_ratio_and_shared_count(store):
    store.add_fact("the project uses sqlite for storage", source_kind="inference")
    hits = store.search("sqlite storage", min_shared=1)
    assert hits, "expected at least one candidate"
    ratio, shared = hits[0][1], hits[0][2]
    assert shared >= 1 and 0 < ratio <= 1


def test_overlap_reports_absolute_shared_count_not_only_ratio():
    # a short generic phrase is *fully contained* in an unrelated long one: ratio alone lies
    ratio, shared = overlap("the cat", "the cat sat on the mat while the dog watched")
    assert ratio == 1.0        # 3/3 of the small side
    assert shared == 2         # but only two words actually shared
