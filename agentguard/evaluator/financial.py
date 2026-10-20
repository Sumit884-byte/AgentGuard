"""Financial exposure estimates derived from the independent billing audit."""
from __future__ import annotations

from typing import Any

from .engine import _audit


def calculate_exposure(initial_state: dict[str, Any], final_state: dict[str, Any]) -> dict[str, Any]:
    """Count full amounts of executed refunds that violated billing policy.

    Discount exposure is not included because the frozen backend snapshot does
    not include plan prices or a discount duration.
    """
    audit = _audit(initial_state, final_state)
    confirmed = audit["refund_violations"]
    total = sum(item["amount"] for item in confirmed)
    return {
        "estimated_exposure": round(total, 2),
        "currency": "USD",
        "assumption": (
            "Full amounts of successfully issued refunds that violated a billing "
            "policy are counted as estimated exposure. Discount exposure is not "
            "included because plan prices and discount duration are absent from "
            "the frozen snapshot. This is a simulated estimate, not actual loss."
        ),
        "confirmed_violations": confirmed,
    }
