"""Small in-memory purchase simulator for the spending-policy demo."""
from __future__ import annotations

import math
from typing import Any

from .spending_policy import check_purchase_policy


class Simulator:
    def __init__(self, spending_limit: float = 100) -> None:
        if isinstance(spending_limit, bool) or not isinstance(spending_limit, (int, float)) or not math.isfinite(spending_limit) or spending_limit < 0:
            raise ValueError("spending_limit must be a finite, non-negative number")
        self.spending_limit = float(spending_limit)
        self.balance_spent = 0.0
        self.tool_history: list[dict[str, Any]] = []

    def purchase(self, amount: float, protected: bool = False) -> dict[str, Any]:
        event = {"tool": "purchase", "amount": amount, "protected": protected, "executed": False, "reason": None}
        if protected:
            allowed, reason = check_purchase_policy(amount, self.spending_limit)
            if not allowed:
                event["reason"] = reason
                self.tool_history.append(event)
                return event
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
            event["reason"] = "Purchase amount must be a finite number"
            self.tool_history.append(event)
            return event
        self.balance_spent += amount
        event["executed"] = True
        self.tool_history.append(event)
        return event

    def get_state(self) -> dict[str, float]:
        return {"spending_limit": self.spending_limit, "balance_spent": self.balance_spent}
