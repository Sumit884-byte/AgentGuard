"""Tool definitions exposed to the LLM and the executor that runs them.

Every call goes to the backend, which returns a decision receipt. The naive
and guarded backends differ only in which policies they enforce. Every
attempt is logged as a ``ToolCallRecord``.
"""

from __future__ import annotations

import json
from typing import Any

from .contracts import BillingBackend
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
    """Runs tool calls against a backend and records each one from its receipt.

    The backend decides (naive or guarded); the executor never enforces
    policy itself. See contracts-v2 section 2 for the receipt-to-record mapping.
    """

    def __init__(self, backend: BillingBackend) -> None:
        self.backend = backend
        self.calls: list[ToolCallRecord] = []

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

        try:
            receipt = getattr(self.backend, name)(**arguments)
        except Exception as exc:  # receipts should cover every case; this catches backend bugs
            record.error = f"{type(exc).__name__}: {exc}"
            return f"Error: {exc}", True

        record.receipt = receipt
        status = receipt.get("status")
        reason = receipt.get("reason") or ""

        if status == "ALLOWED":
            record.executed = True
            record.result = receipt.get("result")
            return json.dumps(record.result, default=str), False

        if status in ("BLOCKED", "NEEDS_APPROVAL"):
            record.allowed = False
            record.policy_reason = f"{receipt.get('violated_policy')}: {reason}"
            say = (receipt.get("safe_alternative") or {}).get("say") or ""
            return f"Blocked by billing policy: {reason} {say}".strip(), True

        # ERROR, or an unknown status: treat as a failed call that did not run.
        record.error = reason or f"Unexpected receipt status: {status!r}"
        return f"Error: {record.error}", True
