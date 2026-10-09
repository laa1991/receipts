"""Command line entry point: ``python -m receipts.cli <command>``."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .agent import Agent
from .llm import MockClient, NebiusClient
from .store import Store


def _store(args) -> Store:
    return Store(args.db or os.environ.get("RECEIPTS_DB", "receipts.db"))


def cmd_smoke(args) -> int:
    from .llm import smoke

    try:
        out = smoke()
    except Exception as exc:  # noqa: BLE001 - the message is the product
        print(f"smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_ask(args) -> int:
    store = _store(args)
    client = MockClient() if args.mock else NebiusClient()
    agent = Agent(client, store, note_root=args.note_root)
    turn = agent.ask(args.question)
    print(turn.answer.render())
    return 0


def cmd_chat(args) -> int:
    store = _store(args)
    client = NebiusClient()
    agent = Agent(client, store, note_root=args.note_root)
    history: list[dict] = []
    print("receipts — type a message, /audit for the self-audit, /quit to leave.")
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            continue
        if question in {"/quit", "/exit"}:
            return 0
        if question == "/audit":
            print(_audit_text(store, args_days()))
            continue
        turn = agent.ask(question, history=history)
        print()
        print(turn.answer.render())
        print()
        history += [{"role": "user", "content": question},
                    {"role": "assistant", "content": turn.answer.text}]


def cmd_remember(args) -> int:
    store = _store(args)
    fact, outcome = store.add_fact(
        args.text, source_kind=args.source_kind, source_ref=args.ref,
        source_excerpt=args.excerpt, falsifier=args.falsifier,
    )
    print(f"{outcome}: {fact.id}  {fact.text}")
    return 0 if outcome != "conflict" else 2


def cmd_recall(args) -> int:
    store = _store(args)
    for fact, ratio, shared in store.search(args.query, limit=args.limit, min_shared=1):
        print(f"{fact.id}  [{fact.status}]  {fact.text}")
        if fact.source_excerpt:
            print(f"    source: {fact.source_kind} / {fact.source_ref or '-'}")
            print(f"    excerpt: {fact.source_excerpt}")
    return 0


def cmd_show(args) -> int:
    store = _store(args)
    try:
        prov = store.provenance(args.fact_id)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(prov, indent=2, ensure_ascii=False))
    return 0


def cmd_conflicts(args) -> int:
    store = _store(args)
    pairs = store.conflicts()
    if not pairs:
        print("no open conflicts")
        return 0
    for a, b in pairs:
        print(f"- {a.id} {a.text!r}\n  vs {b.id} {b.text!r}")
    print("\nresolve with: receipts resolve <keep_id> <drop_id> --reason '...'")
    return 2


def cmd_resolve(args) -> int:
    store = _store(args)
    kept = store.resolve_conflict(keep=args.keep, drop=args.drop, reason=args.reason or "")
    print(f"kept {kept.id}: {kept.text}")
    print(f"dropped {args.drop} (marked superseded, not deleted)")
    return 0


def cmd_audit(args) -> int:
    print(_audit_text(_store(args), args_days()))
    return 0


def _audit_text(store: Store, freshness_days: float = 30.0) -> str:
    lines = ["== self-audit =="]
    pairs = store.conflicts()
    lines.append(f"open conflicts: {len(pairs)}")
    for a, b in pairs:
        lines.append(f"  ! {a.text!r}  vs  {b.text!r}")
    stale = store.stale(freshness_days)
    lines.append(f"live facts not re-checked in {freshness_days:g} days: {len(stale)}")
    for f in stale[:20]:
        lines.append(f"  ~ [{f.id}] {f.text}  (from {f.source_kind}, {f.created_at})")
    live = store.facts()
    pending = store.facts(status="disputed")
    lines.append(f"live facts: {len(live)}")
    lines.append(f"facts awaiting your decision (conflicts): {len(pending)}")
    for f in pending[:20]:
        lines.append(f"  ? [{f.id}] {f.text}")
    return "\n".join(lines)


def args_days() -> float:
    return float(os.environ.get("RECEIPTS_FRESHNESS_DAYS", "30"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="receipts", description=__doc__)
    p.add_argument("--db", default=None, help="sqlite path (default: $RECEIPTS_DB or ./receipts.db)")
    p.add_argument("--note-root", default=None, help="root directory the read_note tool may read")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("smoke", help="one real call against Token Factory")
    s.set_defaults(func=cmd_smoke)

    s = sub.add_parser("ask", help="ask one question")
    s.add_argument("question")
    s.add_argument("--mock", action="store_true", help="offline mock model")
    s.set_defaults(func=cmd_ask)

    s = sub.add_parser("chat", help="interactive")
    s.set_defaults(func=cmd_chat)

    s = sub.add_parser("remember", help="store a fact (with its source)")
    s.add_argument("text")
    s.add_argument("--excerpt", default=None)
    s.add_argument("--ref", default=None)
    s.add_argument("--falsifier", default=None)
    s.add_argument("--source-kind", default="user_statement")
    s.set_defaults(func=cmd_remember)

    s = sub.add_parser("recall", help="search stored facts")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(func=cmd_recall)

    s = sub.add_parser("show", help="full provenance of one fact")
    s.add_argument("fact_id")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("conflicts", help="list open conflicts")
    s.set_defaults(func=cmd_conflicts)

    s = sub.add_parser("resolve", help="decide a conflict (keeps both rows)")
    s.add_argument("keep")
    s.add_argument("drop")
    s.add_argument("--reason", default="")
    s.set_defaults(func=cmd_resolve)

    s = sub.add_parser("audit", help="what can't it back up?")
    s.set_defaults(func=cmd_audit)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
