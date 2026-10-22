
def check_purchase_policy(amount, spending_limit):
    """Check the purchase policy before execution."""

    if amount < 0:
        return False, "Purchase amount cannot be negative"

    if amount > spending_limit:
        return False, "Spending limit exceeded"

    return True, "Policy approved"
