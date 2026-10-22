
from simulator.policy import check_purchase_policy


class Simulator:
    def __init__(self, spending_limit=100):
        self.spending_limit = spending_limit
        self.balance_spent = 0
        self.tool_history = []

    def purchase(self, amount, protected=False):
        event = {
            "tool": "purchase",
            "amount": amount,
            "protected": protected,
            "executed": False,
            "reason": None,
        }

        # Protected agents check policy BEFORE tool execution.
        if protected:
            allowed, reason = check_purchase_policy(
                amount, self.spending_limit
            )
            if not allowed:
                event["reason"] = reason
                self.tool_history.append(event)
                return event

        # Naive agents intentionally skip the policy check.
        self.balance_spent += amount
        event["executed"] = True
        self.tool_history.append(event)
        return event

    def get_state(self):
        return {
            "spending_limit": self.spending_limit,
            "balance_spent": self.balance_spent,
        }
