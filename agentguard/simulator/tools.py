"""Tool definitions exposed to the LLM and the executors that run them.

The naive executor sends every call straight to the backend. The guarded
executor asks the policy engine first and only executes allowed calls. Both
log every attempt as a ``ToolCallRecord``.
"""

from __future__ import annotations

import json
from typing import Any

from .contracts import BillingBackend, PolicyEngine
from .records import ToolCallRecord

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "get_subscription",
        "description": (
            "Look up a customer's subscription: plan, price, status, active "
            "discounts and payment history. Call this before changing anything."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer ID, e.g. C-1001."},
            },
            "required": ["customer_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "apply_discount",
        "description": "Apply a percentage discount to a customer's subscription.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "percent": {"type": "number", "description": "Discount percentage, 0-100."},
                "reason": {"type": "string", "description": "Why the discount is being given."},
            },
            "required": ["customer_id", "percent", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "cancel_subscription",
        "description": "Cancel a customer's subscription.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["customer_id", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "issue_refund",
        "description": "Refund money to a customer's original payment method.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "amount": {"type": "number", "description": "Amount in USD."},
                "reason": {"type": "string"},
            },
            "required": ["customer_id", "amount", "reason"],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = frozenset(spec["name"] for spec in TOOL_SPECS)


class ToolExecutor:
    """Runs tool calls against the backend, optionally through a policy engine.

    With ``policy_engine=None`` this is the naive agent's executor.
    """

    def __init__(
        self,
        backend: BillingBackend,
        context: dict[str, Any],
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self.backend = backend
        self.context = context
        self.policy_engine = policy_engine
        self.calls: list[ToolCallRecord] = []

    @property
    def guarded(self) -> bool:
        return self.policy_engine is not None

    def execute(self, turn: int, tool_use_id: str, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Run one call. Returns ``(content_for_model, is_error)``."""
        record = ToolCallRecord(
            turn=turn,
            tool_use_id=tool_use_id,
            tool_name=name,
            arguments=dict(arguments),
            allowed=True,
            executed=False,
        )
        self.calls.append(record)

        if name not in TOOL_NAMES:
            record.error = f"Unknown tool: {name}"
            return record.error, True

        if self.policy_engine is not None:
            decision = self.policy_engine.check(name, arguments, self.context, self.backend)
            if not decision.allowed:
                record.allowed = False
                record.policy_reason = decision.reason
                return f"Action blocked by billing policy: {decision.reason}", True

        try:
            result = getattr(self.backend, name)(**arguments)
        except Exception as exc:  # backend validation errors surface to the agent
            record.error = f"{type(exc).__name__}: {exc}"
            return f"Error: {exc}", True

        record.executed = True
        record.result = result
        return json.dumps(result, default=str), False
