"""Interface the simulator expects from the backend (Person A).

See contracts-v2 sections 2 and 4. ``make_backend(scenario, mode)`` builds one
of these per run. Every method returns a decision receipt dict and never
raises for policy or argument problems.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

ReceiptStatus = Literal["ALLOWED", "BLOCKED", "NEEDS_APPROVAL", "ERROR"]

# A receipt is a plain dict with these keys (contracts-v2 section 4):
#   receipt_version, mode, status, tool, args, actor_id, sub_id, checks,
#   violated_policy, reason, safe_alternative, approval_id, executed, money, result
Receipt = dict[str, Any]


@runtime_checkable
class BillingBackend(Protocol):
    """The four model-facing billing tools plus a state snapshot for the evaluator.

    The acting customer is fixed when the backend is built (the scenario's
    authenticated customer); it is never taken from tool arguments.
    """

    def get_subscription(self, customer_id: str) -> Receipt: ...

    def apply_discount(self, customer_id: str, percent: float, reason: str) -> Receipt: ...

    def cancel_subscription(self, customer_id: str, reason: str) -> Receipt: ...

    def issue_refund(self, customer_id: str, amount: float, reason: str) -> Receipt: ...

    def snapshot(self) -> dict[str, Any]:
        """Return a deep copy of the full database state."""
        ...
