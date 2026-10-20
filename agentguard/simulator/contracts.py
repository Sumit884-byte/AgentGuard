"""Interfaces the simulator expects from the backend (Member 1).

The simulator never imports the backend directly. Anything that satisfies
these protocols can be plugged in, which keeps this module testable before
the real billing database and policy engine land.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BillingBackend(Protocol):
    """The four core billing tools plus a state snapshot for the evaluator.

    Each tool returns a JSON-serialisable dict and raises an exception on
    invalid input (unknown customer, bad amount, ...). The simulator turns
    exceptions into tool errors the agent can see.
    """

    def get_subscription(self, customer_id: str) -> dict[str, Any]: ...

    def apply_discount(self, customer_id: str, percent: float, reason: str) -> dict[str, Any]: ...

    def cancel_subscription(self, customer_id: str, reason: str) -> dict[str, Any]: ...

    def issue_refund(self, customer_id: str, amount: float, reason: str) -> dict[str, Any]: ...

    def snapshot(self) -> dict[str, Any]:
        """Return a deep copy of the full database state."""
        ...


@runtime_checkable
class PolicyDecision(Protocol):
    allowed: bool
    reason: str


@runtime_checkable
class PolicyEngine(Protocol):
    """Validates a tool call before it reaches the backend.

    ``context`` carries session facts the policy checks need, e.g.
    ``authenticated_customer_id`` and ``scenario_id``. ``backend`` is passed
    so checks can read current state (existing discounts, amount paid, ...).
    """

    def check(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
        backend: BillingBackend,
    ) -> PolicyDecision: ...
