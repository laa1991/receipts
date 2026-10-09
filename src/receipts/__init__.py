"""Receipts — a personal AI that shows its work."""

from .store import Store, Fact, ACTIVE, RETRACTED, SUPERSEDED, DISPUTED
from .receipts import (
    Claim,
    Answer,
    Receipt,
    audit_lines,
    computation_receipt,
    fact_receipt,
    none_receipt,
    quote_receipt,
    tool_receipt,
    CONTRADICTED,
    STALE,
    UNVERIFIED,
    VERIFIED,
)

__all__ = [
    "Store", "Fact", "ACTIVE", "RETRACTED", "SUPERSEDED", "DISPUTED",
    "Claim", "Answer", "Receipt", "audit_lines",
    "computation_receipt", "fact_receipt", "none_receipt", "quote_receipt", "tool_receipt",
    "CONTRADICTED", "STALE", "UNVERIFIED", "VERIFIED",
]
__version__ = "0.1.0"
