"""The receipt model: what it means for a claim to be backed.

A *claim* is one assertion the assistant makes in an answer ("you prefer X", "the file has
1,204 rows", "I saved it"). A *receipt* is the evidence attached to that claim. The four
statuses are deliberately not booleans:

  verified      backed, and re-checked under the stated method
  stale         backed once, but not re-checked within the freshness window
  unverified    no backing at all — the honest state for "I don't actually know"
  contradicted  the evidence we do have says the claim is wrong

Every receipt carries a ``verify_command``: something the *reader* can run to re-check it.
If a claim cannot produce one, that is itself the finding — and it is counted.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Sequence

VERIFIED = "verified"
STALE = "stale"
UNVERIFIED = "unverified"
CONTRADICTED = "contradicted"

STATUS_ORDER = {CONTRADICTED: 3, UNVERIFIED: 2, STALE: 1, VERIFIED: 0}

KINDS = ("fact", "tool", "computation", "quote", "none")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Receipt:
    kind: str
    evidence: dict
    status: str
    verify_command: str | None = None
    note: str = ""
    checked_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown receipt kind {self.kind!r}; expected one of {KINDS}")
        if self.status not in STATUS_ORDER:
            raise ValueError(f"unknown status {self.status!r}")

    def line(self) -> str:
        mark = {VERIFIED: "OK ", STALE: "AGE", UNVERIFIED: "?? ", CONTRADICTED: "XX "}[self.status]
        cmd = f"  ↳ re-check: {self.verify_command}" if self.verify_command else ""
        return f"[{mark}] {self.kind}: {self.note}{cmd}"


@dataclass
class Claim:
    text: str
    receipts: list[Receipt] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.receipts:
            return UNVERIFIED
        return max((r.status for r in self.receipts), key=lambda s: STATUS_ORDER[s])

    @property
    def receipt(self) -> Receipt | None:
        """The receipt that decided the status (worst one first)."""
        if not self.receipts:
            return None
        return max(self.receipts, key=lambda r: STATUS_ORDER[r.status])


@dataclass
class Answer:
    question: str
    text: str
    claims: list[Claim] = field(default_factory=list)
    at: str = field(default_factory=_now)

    def counts(self) -> dict[str, int]:
        out = {VERIFIED: 0, STALE: 0, UNVERIFIED: 0, CONTRADICTED: 0}
        for c in self.claims:
            out[c.status] += 1
        return out

    def overclaim_rate(self) -> float:
        """Share of claims that are not properly backed (stale counts as a miss)."""
        if not self.claims:
            return 0.0
        bad = self.counts()[UNVERIFIED] + self.counts()[CONTRADICTED] + self.counts()[STALE]
        return bad / len(self.claims)

    def render(self) -> str:
        lines = [f"Q: {self.question}", f"A: {self.text}", "", "Receipts:"]
        if not self.claims:
            lines.append("  (no claims extracted — nothing asserted)")
        for c in self.claims:
            lines.append(f"  · {c.text}  → {c.status}")
            if c.receipt:
                lines.append("    " + c.receipt.line())
        c = self.counts()
        lines.append("")
        lines.append(
            f"  verified {c[VERIFIED]} · stale {c[STALE]} · "
            f"unverified {c[UNVERIFIED]} · contradicted {c[CONTRADICTED]}"
        )
        return "\n".join(lines)


# --- receipt builders -------------------------------------------------------------------


def fact_receipt(store, fact_id: str, freshness_days: float = 30.0) -> Receipt:
    """A receipt pointing at a stored fact. Missing or dead facts are *not* silent."""
    f = store.get_or_none(fact_id)
    if f is None:
        return Receipt("fact", {"fact_id": fact_id}, CONTRADICTED,
                       note=f"fact {fact_id} no longer exists", verify_command=None)
    ev = {"fact_id": f.id, "status": f.status, "source": f.source_kind,
          "source_ref": f.source_ref, "excerpt": f.source_excerpt}
    if f.status == "retracted":
        status = CONTRADICTED
    elif f.status == "disputed":
        status = CONTRADICTED
    elif f.status == "superseded":
        status = STALE
    else:
        status = VERIFIED if f.is_fresh(freshness_days) else STALE
    return Receipt("fact", ev, status,
                   note=f"{f.text!r} (from {f.source_kind})",
                   verify_command=f"python -m receipts.cli show {f.id}")


def tool_receipt(command: str, exit_code: int, stdout: str, claim_says_success: bool = True) -> Receipt:
    """A receipt for a claim about something that ran."""
    digest = sha256_text(stdout)
    ev = {"command": command, "exit_code": exit_code, "stdout_sha256": digest,
          "stdout_excerpt": stdout[-400:]}
    if exit_code != 0 and claim_says_success:
        status = CONTRADICTED
    elif exit_code != 0:
        status = VERIFIED  # the claim was about the failure, and the failure is evidenced
    else:
        status = VERIFIED
    return Receipt("tool", ev, status, note=f"`{command}` → exit {exit_code}, sha {digest[:12]}",
                   verify_command=command)


def computation_receipt(expression: str, result: object) -> Receipt:
    ev = {"expression": expression, "result": result}
    return Receipt("computation", ev, VERIFIED, note=f"{expression} = {result}",
                   verify_command=f'python -c "print({expression})"')


def quote_receipt(source: str, excerpt: str) -> Receipt:
    ev = {"source": source, "excerpt": excerpt, "sha256": sha256_text(excerpt)}
    return Receipt("quote", ev, VERIFIED, note=f"{source}: {excerpt[:80]!r}",
                   verify_command=f"grep -n -- {excerpt[:40]!r} {source}")


def none_receipt(why: str) -> Receipt:
    """The explicit 'I have nothing' — this is the state the whole project is about."""
    return Receipt("none", {"why": why}, UNVERIFIED, note=why, verify_command=None)


def audit_lines(answer: Answer) -> list[str]:
    """The self-audit view: only what could not be backed."""
    out = []
    for c in answer.claims:
        if c.status != VERIFIED:
            r = c.receipt
            out.append(f"- [{c.status}] {c.text}" + (f"  ({r.note})" if r else ""))
    return out or ["- (everything asserted carries a receipt)"]


def worst(claims: Iterable[Claim]) -> str:
    claims = list(claims)
    if not claims:
        return VERIFIED
    return max((c.status for c in claims), key=lambda s: STATUS_ORDER[s])
