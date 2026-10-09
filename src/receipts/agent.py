"""The assistant loop: tool calls in, receipts out.

Design notes that matter for the demo:

* Every tool the model calls produces a :class:`ToolRun` **and** a receipt. The receipt is
  built from what actually happened (exit code, output hash, fact id), never from what the
  model says happened.
* The final answer is passed through a **claim extraction** step which maps each assertion
  onto the receipts collected during the turn. A claim with no matching receipt is
  ``unverified`` — that is the number this project exists to make visible.
* Contradictions are surfaced, not resolved silently: if ``remember`` returns ``conflict``,
  the loop tells the model, and the answer must say so.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .llm import NebiusClient, Reply
from .receipts import (
    Answer,
    Claim,
    Receipt,
    computation_receipt,
    fact_receipt,
    none_receipt,
    quote_receipt,
    tool_receipt,
)
from .store import Store

SYSTEM_PROMPT = """You are a personal assistant whose memory is auditable.

Hard rules:
1. Anything you state as fact must be backed by one of your tools: `recall` (a stored fact),
   `compute` (a calculation you actually ran), or `read_note` (an excerpt you actually read).
2. If you cannot back a statement, say plainly that you don't know, or that it is unverified.
   Never present a guess as a fact.
3. When the user tells you something that may contradict what you have stored, call `remember`
   and let the store decide. If it reports a conflict, tell the user both versions and ask
   which one holds. Never overwrite silently.
4. Keep the answer short. Do not claim to have done something you did not do in this turn.
5. Read tool results literally. A `remember` result also tells you what was compared: if it
   says nothing overlapped to compare, you may NOT claim "there is no conflict" — say what
   was checked and what was not.
"""

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Store a durable fact about the user or their world, with its source.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The fact, as a single sentence."},
                    "excerpt": {"type": "string", "description": "The verbatim words it came from."},
                    "source_ref": {"type": "string", "description": "Where it came from, e.g. 'chat 2026-10-09'."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Look up stored facts related to a question.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute",
            "description": "Evaluate an arithmetic expression to get a number you can cite.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "e.g. '1234 / 7'"}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_note",
            "description": "Read lines from a local note file to quote it accurately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_lines": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_conflicts",
            "description": "List memory conflicts awaiting a human decision.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


@dataclass
class ToolRun:
    name: str
    arguments: dict
    result: str
    receipt: Receipt


@dataclass
class Turn:
    question: str
    answer: Answer
    tool_runs: list[ToolRun] = field(default_factory=list)
    steps: int = 0


# --- claim extraction -------------------------------------------------------------------


CLAIM_PROMPT = """You are auditing an assistant's answer for unsupported claims.

Answer:
{answer}

Evidence available this turn (each has an id):
{ledger}

Return JSON only:
{{"claims": [{{"text": "<one factual assertion from the answer, quoted or paraphrased>",
               "evidence": ["<evidence id>", ...]}}]}}

Rules:
- Split the answer into its distinct factual assertions. Opinions, questions and hedges are
  not claims.
- An assertion with no supporting evidence gets an empty list. Do not invent support.
- A receipt only supports what it actually did. A `remember` receipt reports that a fact was
  stored and what it was compared against; it does NOT support a claim that no conflict exists
  if the comparison found nothing to compare with.
- If the answer contains no factual assertions, return {{"claims": []}}.
"""


def fallback_claims(answer_text: str) -> list[dict]:
    """No model available: sentence split, no evidence attached.

    Deliberately pessimistic — with nothing to check against, every assertion is unsupported.
    """
    parts = [p.strip() for p in re.split(r"(?<=[.!?。！？\n])\s*", answer_text) if p.strip()]
    return [{"text": p, "evidence": []} for p in parts]


class Agent:
    def __init__(
        self,
        client: NebiusClient | Any,
        store: Store,
        freshness_days: float = 30.0,
        note_root: str | None = None,
        max_steps: int = 6,
        extractor: Callable[[str, dict[str, Receipt]], list[dict]] | None = None,
        model_judge: bool = True,
        recent_window: int = 20,
    ) -> None:
        self.client = client
        self.store = store
        self.freshness_days = freshness_days
        self.note_root = note_root
        self.max_steps = max_steps
        self._extractor = extractor
        self._use_model_judge = model_judge
        self.recent_window = recent_window

    # --- tools --------------------------------------------------------------------------

    def _run_tool(self, name: str, args: dict) -> ToolRun:
        if name == "remember":
            fact, outcome = self.store.add_fact(
                text=args.get("text", ""),
                source_kind="user_statement",
                source_ref=args.get("source_ref"),
                source_excerpt=args.get("excerpt"),
                judge=self._judge if self._use_model_judge else None,
                recent=self.recent_window if self._use_model_judge else 0,
                batch_judge=self._judge_batch if self._use_model_judge else None,
            )
            if outcome == "conflict":
                others = [{"id": o.id, "text": o.text} for o in self.store.conflicts_for(fact.id)]
                result = json.dumps(
                    {"outcome": "conflict", "new_fact": fact.id, "conflicting": others},
                    ensure_ascii=False,
                )
                rc = 1
            elif outcome == "duplicate":
                result = json.dumps({"outcome": "duplicate", "fact": fact.id, "text": fact.text},
                                    ensure_ascii=False)
                rc = 0
            else:
                result = json.dumps({"outcome": "added", "fact": fact.id, "text": fact.text},
                                    ensure_ascii=False)
                rc = 0
            # The exit code here describes the *store's* outcome, not the answer's honesty:
            # a conflict is a truthful result, so `claim_says_success=False` keeps the
            # receipt usable while the JSON carries what actually happened.
            receipt = tool_receipt(f"remember({fact.id})", rc, result, claim_says_success=False)
            receipt.note = (f"remember → {run_outcome_text(outcome, fact)} · "
                            f"{check_text(self.store.last_check)}")
            receipt.verify_command = (
                "python -m receipts.cli conflicts" if outcome == "conflict"
                else f"python -m receipts.cli show {fact.id}"
            )
            receipts = [receipt]
            if outcome != "conflict":
                receipts.append(fact_receipt(self.store, fact.id, self.freshness_days))
            return ToolRun(name, args, result, _combine(receipts, receipts[0]))

        if name == "recall":
            # Deliberately permissive: missing a fact you actually hold is worse than
            # returning a weak candidate, because the receipt's status already says how
            # solid it is (verified / stale / disputed).
            hits = self.store.search(
                args.get("query", ""),
                limit=int(args.get("limit", 5)),
                min_shared=int(args.get("min_shared", 1)),
            )
            payload = [{"id": f.id, "text": f.text, "source": f.source_kind,
                        "source_ref": f.source_ref, "excerpt": f.source_excerpt,
                        "status": f.status, "checked": f.verified_at}
                       for f, _r, _s in hits]
            result = json.dumps({"hits": payload}, ensure_ascii=False)
            receipts = [fact_receipt(self.store, h["id"], self.freshness_days) for h in payload]
            run = ToolRun(name, args, result, tool_receipt(f"recall({args.get('query','')})", 0, result))
            run.receipt = _combine(receipts, run.receipt)
            return run

        if name == "compute":
            expr = str(args.get("expression", ""))
            result, rc = _safe_eval(expr)
            # a failed computation may never back a numeric claim ⇒ contradicted, not "fine"
            receipt = computation_receipt(expr, result) if rc == 0 else tool_receipt(
                f"compute({expr})", rc, str(result))
            return ToolRun(name, args, json.dumps({"result": result}, ensure_ascii=False), receipt)

        if name == "read_note":
            path = str(args.get("path", ""))
            try:
                lines = _read_note(path, self.note_root, int(args.get("max_lines", 40)))
                text = "".join(lines)
                excerpt = lines[0].strip()[:120] if lines else ""
                receipt = quote_receipt(path, excerpt) if excerpt else none_receipt(
                    f"{path} is empty")
                return ToolRun(name, args, json.dumps({"lines": len(lines), "text": text},
                                                      ensure_ascii=False), receipt)
            except OSError as exc:
                return ToolRun(name, args, json.dumps({"error": str(exc)}, ensure_ascii=False),
                               none_receipt(f"could not read {path}: {exc}"))

        if name == "list_conflicts":
            pairs = self.store.conflicts()
            payload = [{"a": a.text, "b": b.text, "ids": [a.id, b.id]} for a, b in pairs]
            result = json.dumps({"conflicts": payload}, ensure_ascii=False)
            return ToolRun(name, args, result, tool_receipt("list_conflicts", 0, result))

        return ToolRun(name, args, json.dumps({"error": f"unknown tool {name}"}),
                       none_receipt(f"unknown tool {name}"))

    def _judge(self, existing: str, incoming: str) -> str:  # pragma: no cover - needs a model
        prompt = (
            "Two statements about the same person. Answer with one word:\n"
            "'same' if they say the same thing, 'contradict' if they cannot both be true, "
            "'unrelated' otherwise.\n"
            f"A: {existing}\nB: {incoming}\n"
        )
        reply = self.client.chat([{"role": "user", "content": prompt}], max_tokens=8,
                                 temperature=0.0)
        word = reply.text.strip().lower()
        for verdict in ("contradict", "same", "unrelated"):
            if verdict in word:
                return verdict
        return "unrelated"

    def _judge_batch(self, candidates: list, incoming: str) -> list[str]:
        """One call over the whole candidate pool: which existing facts cannot both be true?

        Batched on purpose. The reason a recency window is needed at all is that lexical
        overlap misses "I moved to Berlin" vs "Robin lives in Porto"; but judging that
        window pair-by-pair would cost one round trip per fact on every `remember`.
        """
        listing = "\n".join(f"- {f.id}: {f.text}" for f in candidates)
        prompt = (
            "A new statement is about to be stored about a person.\n\n"
            f"New statement: {incoming}\n\n"
            f"Existing statements:\n{listing}\n\n"
            "List the ids of existing statements that describe the SAME attribute about the "
            "person with a DIFFERENT value — i.e. the new statement looks like an update of "
            "them (an old home city vs a new home city; an old employer vs a new one).\n"
            "Rules:\n"
            "- Same attribute, different value ⇒ list the id, even if both could technically "
            "be true at different times. The user has to confirm which one holds now.\n"
            "- Different attribute, or a compatible detail (city vs district, job vs team) ⇒ "
            "do not list it.\n"
            "- Answer with the ids only, one per line. If none apply, answer exactly: NONE"
        )
        reply = self.client.chat([{"role": "user", "content": prompt}], temperature=0.0,
                                 max_tokens=256)
        text = reply.text or ""
        wanted = set(re.findall(r"f_[0-9a-f]{6,}", text))
        if not wanted:
            return []
        return [f.id for f in candidates if f.id in wanted]

    # --- the loop -----------------------------------------------------------------------

    def ask(self, question: str, history: Sequence[dict] | None = None) -> Turn:
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages += list(history or [])
        messages.append({"role": "user", "content": question})

        runs: list[ToolRun] = []
        text = ""
        steps = 0
        for step in range(self.max_steps):
            steps = step + 1
            reply: Reply = self.client.chat(messages, tools=TOOLS)
            if not reply.tool_calls:
                text = reply.text
                break
            messages.append(_assistant_tool_message(reply))
            for call in reply.tool_calls:
                run = self._run_tool(call.name, call.arguments)
                runs.append(run)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": run.result})
        else:
            text = "(stopped: reached the step limit without reaching an answer)"

        ledger = {f"e{i+1}": r.receipt for i, r in enumerate(runs)}
        claims = self._extract(text, ledger)
        answer = Answer(question=question, text=text, claims=claims)
        return Turn(question=question, answer=answer, tool_runs=runs, steps=steps)

    def _extract(self, text: str, ledger: dict[str, Receipt]) -> list[Claim]:
        if not text.strip():
            return []
        if self._extractor is not None:
            raw = self._extractor(text, ledger)
        else:
            ledger_text = "\n".join(
                f"{eid}: [{r.kind}/{r.status}] {r.note}" for eid, r in ledger.items()
            ) or "(no evidence gathered this turn)"
            reply = self.client.chat(
                [{"role": "user", "content": CLAIM_PROMPT.format(answer=text, ledger=ledger_text)}],
                temperature=0.0,
                max_tokens=1024,
            )
            raw = _parse_claims(reply.text) or fallback_claims(text)

        claims: list[Claim] = []
        for item in raw:
            receipts = [ledger[e] for e in item.get("evidence", []) if e in ledger]
            if not receipts:
                receipts = [none_receipt("no evidence gathered for this claim")]
            claims.append(Claim(text=str(item.get("text", "")).strip(), receipts=receipts))
        return claims


# --- helpers ----------------------------------------------------------------------------


def _combine(receipts: list[Receipt], fallback: Receipt) -> Receipt:
    """Pick the receipt that carries the most information about a multi-hit tool call."""
    if not receipts:
        return fallback
    order = {"contradicted": 3, "unverified": 2, "stale": 1, "verified": 0}
    return max(receipts, key=lambda r: order[r.status])


def run_outcome_text(outcome: str, fact) -> str:
    """Plain-language note for a `remember` receipt — what the store actually did."""
    if outcome == "added":
        return f"stored a new fact ({fact.id}); nothing was replaced"
    if outcome == "duplicate":
        return f"already had this fact ({fact.id}); nothing was added"
    return (f"CONFLICT — both versions are kept ({fact.id} and the earlier one) "
            f"and the question is yours to settle")


def check_text(check: dict) -> str:
    """Plain-language account of what a `remember` actually compared.

    This exists because the first live run produced a *false* "no conflict" claim: the receipt
    said "stored a new fact" and the sentence built on it said "nothing conflicts". A receipt
    must therefore carry the check itself — including the case where nothing was compared.
    """
    n = int(check.get("candidates", 0))
    checker = check.get("checker", "none")
    verdicts = check.get("verdicts", [])
    if checker == "none" or n == 0:
        return ("nothing in memory overlapped enough to compare — this is NOT a "
                "no-conflict check")
    parts = []
    if check.get("lexical"):
        parts.append(f"{check['lexical']} by word overlap")
    if check.get("recent"):
        parts.append(f"{check['recent']} from the recency window")
    detail = ", ".join(f"{cid}:{v}" for cid, v in verdicts)
    return (f"compared {n} existing fact(s) ({' + '.join(parts) or 'pool'}) "
            f"via {checker} [{detail}]")


def _assistant_tool_message(reply: Reply) -> dict:
    return {
        "role": "assistant",
        "content": reply.text or "",
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)},
            }
            for c in reply.tool_calls
        ],
    }


_ALLOWED = set("0123456789+-*/(). %eE")


def _safe_eval(expression: str) -> tuple[Any, int]:
    """Arithmetic only. A calculator, not an interpreter."""
    if not expression or set(expression) - _ALLOWED:
        return f"refused: only arithmetic is allowed, got {expression!r}", 1
    try:
        value = eval(expression, {"__builtins__": {}}, {})  # noqa: S307 - charset-guarded above
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}", 1
    return value, 0


def _read_note(path: str, root: str | None, max_lines: int) -> list[str]:
    from pathlib import Path

    p = Path(path)
    if root and not p.is_absolute():
        p = Path(root) / p
    if root:
        resolved, base = p.resolve(), Path(root).resolve()
        if base not in resolved.parents and resolved != base:
            raise OSError(f"{path} is outside the note root")
    out: list[str] = []
    with p.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= max_lines:
                break
            out.append(line)
    return out


def _parse_claims(raw: str) -> list[dict]:
    if not raw:
        return []
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    claims = data.get("claims")
    return claims if isinstance(claims, list) else []
