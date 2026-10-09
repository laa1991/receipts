"""Memory with provenance.

Three rules this module exists to enforce:

  R1  Every fact carries its source — kind, ref, and the verbatim excerpt it came from.
  R2  Nothing is silently overwritten. A contradicting fact raises a conflict and waits
      for a human decision; the old fact survives until it is retracted or superseded.
  R3  ``unknown`` is a first-class state. A fact that was never re-checked is *unverified*,
      which is not the same as *false* and not the same as *true*.

The store is a single SQLite file plus an append-only event log: every mutation writes a
line to ``events``, so the history of what the assistant knew, when, and why is auditable
after the fact.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

# --- states -----------------------------------------------------------------------------

ACTIVE = "active"
RETRACTED = "retracted"
SUPERSEDED = "superseded"
DISPUTED = "disputed"

SOURCE_KINDS = ("user_statement", "file", "url", "tool_output", "inference")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
  id             TEXT PRIMARY KEY,
  text           TEXT NOT NULL,
  source_kind    TEXT NOT NULL,
  source_ref     TEXT,
  source_excerpt TEXT,
  created_at     TEXT NOT NULL,
  verified_at    TEXT,
  status         TEXT NOT NULL DEFAULT 'active',
  superseded_by  TEXT,
  falsifier      TEXT,
  tags           TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(status);

CREATE TABLE IF NOT EXISTS links (
  src  TEXT NOT NULL,
  dst  TEXT NOT NULL,
  kind TEXT NOT NULL,          -- 'conflict' | 'supersedes'
  at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  seq     INTEGER PRIMARY KEY AUTOINCREMENT,
  at      TEXT NOT NULL,
  kind    TEXT NOT NULL,
  fact_id TEXT,
  payload TEXT NOT NULL
);
"""


def now() -> str:
    """UTC timestamp, second precision, ISO-8601 with a trailing Z."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str = "f") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


_WORD = re.compile(r"[a-z0-9\u4e00-\u9fff]+", re.I)


def tokens(text: str) -> list[str]:
    """Lower-cased word-ish tokens. Cheap, language-agnostic enough for candidate lookup."""
    return [t.lower() for t in _WORD.findall(text or "")]


def overlap(a: str, b: str) -> tuple[float, int]:
    """(overlap ratio over the smaller side, number of shared tokens).

    Ratio alone is not enough: a short generic phrase is *fully contained* in a long
    unrelated one. We therefore always report the absolute shared count too, and callers
    use both (the same lesson that produced this project's dedupe thresholds).
    """
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return 0.0, 0
    common = ta & tb
    return len(common) / min(len(ta), len(tb)), len(common)


@dataclass
class Fact:
    id: str
    text: str
    source_kind: str
    source_ref: str | None
    source_excerpt: str | None
    created_at: str
    verified_at: str | None
    status: str
    superseded_by: str | None
    falsifier: str | None
    tags: list[str]

    def age_days(self, at: str | None = None) -> float:
        ref = datetime.fromisoformat((at or now()).replace("Z", "+00:00"))
        made = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        return (ref - made).total_seconds() / 86400.0

    def is_fresh(self, freshness_days: float, at: str | None = None) -> bool:
        stamp = self.verified_at or self.created_at
        ref = datetime.fromisoformat((at or now()).replace("Z", "+00:00"))
        seen = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return (ref - seen) <= timedelta(days=freshness_days)


def _row_to_fact(row: sqlite3.Row) -> Fact:
    return Fact(
        id=row["id"],
        text=row["text"],
        source_kind=row["source_kind"],
        source_ref=row["source_ref"],
        source_excerpt=row["source_excerpt"],
        created_at=row["created_at"],
        verified_at=row["verified_at"],
        status=row["status"],
        superseded_by=row["superseded_by"],
        falsifier=row["falsifier"],
        tags=json.loads(row["tags"] or "[]"),
    )


class Store:
    """Facts + provenance + retraction + conflicts."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self.db.commit()

    # --- events -------------------------------------------------------------------------

    def _log(self, kind: str, fact_id: str | None, payload: dict) -> None:
        self.db.execute(
            "INSERT INTO events(at, kind, fact_id, payload) VALUES (?,?,?,?)",
            (now(), kind, fact_id, json.dumps(payload, ensure_ascii=False)),
        )

    def events(self, fact_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM events"
        args: tuple = ()
        if fact_id:
            sql += " WHERE fact_id = ?"
            args = (fact_id,)
        sql += " ORDER BY seq"
        return [dict(r) for r in self.db.execute(sql, args)]

    # --- writing ------------------------------------------------------------------------

    def add_fact(
        self,
        text: str,
        source_kind: str,
        source_ref: str | None = None,
        source_excerpt: str | None = None,
        falsifier: str | None = None,
        tags: Sequence[str] = (),
        judge: Callable[[str, str], str] | None = None,
        min_shared: int = 3,
        ratio: float = 0.6,
    ) -> tuple[Fact, str]:
        """Store a fact. Returns ``(fact, outcome)`` where outcome is one of:

        ``added`` · ``duplicate`` (an equivalent fact already exists) ·
        ``conflict`` (a candidate contradicts it; both are marked and a decision is needed)
        """
        if source_kind not in SOURCE_KINDS:
            raise ValueError(f"unknown source_kind {source_kind!r}; expected one of {SOURCE_KINDS}")
        if not (text or "").strip():
            raise ValueError("refusing to store an empty fact")

        candidates = self._candidates(text, min_shared=min_shared)
        for cand in candidates:
            same_ratio, shared = overlap(text, cand.text)
            verdict = None
            if judge is not None:
                verdict = judge(cand.text, text)
            elif same_ratio >= ratio and shared >= min_shared:
                verdict = "same"
            if verdict == "same":
                self._log("fact.duplicate", cand.id, {"incoming": text})
                self.db.commit()
                return cand, "duplicate"
            if verdict == "contradict":
                return self._raise_conflict(cand, text, source_kind, source_ref,
                                            source_excerpt, falsifier, tags)

        fact = self._insert(text, source_kind, source_ref, source_excerpt, falsifier, tags)
        self._log("fact.added", fact.id, {"text": text, "source_kind": source_kind,
                                          "source_ref": source_ref})
        self.db.commit()
        return fact, "added"

    def _insert(self, text, source_kind, source_ref, source_excerpt, falsifier, tags) -> Fact:
        fid = new_id()
        self.db.execute(
            "INSERT INTO facts(id,text,source_kind,source_ref,source_excerpt,created_at,"
            "status,falsifier,tags) VALUES (?,?,?,?,?,?,?,?,?)",
            (fid, text, source_kind, source_ref, source_excerpt, now(), ACTIVE, falsifier,
             json.dumps(list(tags), ensure_ascii=False)),
        )
        return self.get(fid)

    def _raise_conflict(self, cand: Fact, text, source_kind, source_ref,
                        source_excerpt, falsifier, tags) -> tuple[Fact, str]:
        new = self._insert(text, source_kind, source_ref, source_excerpt, falsifier, tags)
        at = now()
        self.db.execute("INSERT INTO links(src,dst,kind,at) VALUES (?,?,?,?)",
                        (cand.id, new.id, "conflict", at))
        for fid in (cand.id, new.id):
            self.db.execute("UPDATE facts SET status=? WHERE id=?", (DISPUTED, fid))
        # the event goes on *both* rows: auditing the loser must show why it lost
        for fid, other, own_text in ((new.id, cand.id, text), (cand.id, new.id, cand.text)):
            self._log("fact.conflict", fid, {"with": other, "text": own_text})
        self.db.commit()
        return new, "conflict"

    def resolve_conflict(self, keep: str, drop: str, reason: str = "") -> Fact:
        """Human decision: keep one side, retract the other. Nothing is deleted."""
        keep_f, drop_f = self.get(keep), self.get(drop)
        if keep_f.status == RETRACTED or drop_f.status == RETRACTED:
            raise ValueError("both sides must be live to resolve a conflict")
        at = now()
        self.db.execute("UPDATE facts SET status=?, superseded_by=?, verified_at=? WHERE id=?",
                        (SUPERSEDED, keep_f.id, at, drop_f.id))
        self.db.execute("UPDATE facts SET status=?, verified_at=? WHERE id=?",
                        (ACTIVE, at, keep_f.id))
        self.db.execute("INSERT INTO links(src,dst,kind,at) VALUES (?,?,?,?)",
                        (drop_f.id, keep_f.id, "supersedes", at))
        for fid, other, role in ((keep_f.id, drop_f.id, "kept"), (drop_f.id, keep_f.id, "dropped")):
            self._log("fact.conflict_resolved", fid,
                      {"other": other, "role": role, "reason": reason})
        self.db.commit()
        return self.get(keep_f.id)

    def retract(self, fact_id: str, reason: str) -> Fact:
        self.db.execute("UPDATE facts SET status=? WHERE id=?", (RETRACTED, fact_id))
        self._log("fact.retracted", fact_id, {"reason": reason})
        self.db.commit()
        return self.get(fact_id)

    def verify(self, fact_id: str, method: str, ok: bool = True) -> Fact:
        """Mark a fact as re-checked *now*. ``ok=False`` marks it contradicted."""
        self.db.execute("UPDATE facts SET verified_at=?, status=? WHERE id=?",
                        (now(), ACTIVE if ok else DISPUTED, fact_id))
        self._log("fact.verified", fact_id, {"method": method, "ok": ok})
        self.db.commit()
        return self.get(fact_id)

    # --- reading ------------------------------------------------------------------------

    def get(self, fact_id: str) -> Fact:
        row = self.db.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone()
        if row is None:
            raise KeyError(f"no such fact: {fact_id}")
        return _row_to_fact(row)

    def get_or_none(self, fact_id: str) -> Fact | None:
        try:
            return self.get(fact_id)
        except KeyError:
            return None

    def facts(self, status: str | Iterable[str] | None = ACTIVE) -> list[Fact]:
        if status is None:
            rows = self.db.execute("SELECT * FROM facts ORDER BY created_at").fetchall()
        else:
            wanted = [status] if isinstance(status, str) else list(status)
            marks = ",".join("?" * len(wanted))
            rows = self.db.execute(
                f"SELECT * FROM facts WHERE status IN ({marks}) ORDER BY created_at", wanted
            ).fetchall()
        return [_row_to_fact(r) for r in rows]

    def search(self, query: str, limit: int = 5, min_shared: int = 2) -> list[tuple[Fact, float, int]]:
        scored = []
        for f in self.facts(status=None):
            ratio, shared = overlap(query, f.text)
            if shared >= min_shared:
                scored.append((f, ratio, shared))
        scored.sort(key=lambda t: (t[1], t[2]), reverse=True)
        return scored[:limit]

    def _candidates(self, text: str, min_shared: int = 3) -> list[Fact]:
        return [f for f, _r, _s in self.search(text, limit=5, min_shared=min_shared)]

    def conflicts(self) -> list[tuple[Fact, Fact]]:
        rows = self.db.execute("SELECT src,dst FROM links WHERE kind='conflict'").fetchall()
        out = []
        for r in rows:
            a, b = self.get_or_none(r["src"]), self.get_or_none(r["dst"])
            if a and b and a.status != SUPERSEDED and b.status != SUPERSEDED:
                out.append((a, b))
        return out

    def conflicts_for(self, fact_id: str) -> list[Fact]:
        """The other side(s) of any open conflict involving ``fact_id``."""
        rows = self.db.execute(
            "SELECT src, dst FROM links WHERE kind='conflict' AND (src=? OR dst=?)",
            (fact_id, fact_id),
        ).fetchall()
        out = []
        for r in rows:
            other = r["dst"] if r["src"] == fact_id else r["src"]
            f = self.get_or_none(other)
            if f is not None:
                out.append(f)
        return out

    def stale(self, freshness_days: float = 30.0) -> list[Fact]:
        return [f for f in self.facts(ACTIVE) if not f.is_fresh(freshness_days)]

    def provenance(self, fact_id: str) -> dict:
        f = self.get(fact_id)
        return {
            "fact": f.text,
            "stated": f.created_at,
            "last_checked": f.verified_at,
            "source": {"kind": f.source_kind, "ref": f.source_ref, "excerpt": f.source_excerpt},
            "status": f.status,
            "falsifier": f.falsifier,
            "history": [e for e in self.events(fact_id)],
        }

    def close(self) -> None:
        self.db.close()
