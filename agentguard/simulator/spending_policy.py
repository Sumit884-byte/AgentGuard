"""Pre-execution checks for simulated purchases."""
import math


def check_purchase_policy(amount, spending_limit):
    """Return whether a finite, non-negative purchase is within its limit."""
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
        return False, "Purchase amount must be a finite number"
    if amount < 0:
        return False, "Purchase amount cannot be negative"
    if amount > spending_limit:
        return False, "Spending limit exceeded"
    return True, "Policy approved"
