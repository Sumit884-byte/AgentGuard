"""The four billing tools, with deterministic policy enforcement."""
from __future__ import annotations

import inspect
import math
from typing import Any

from .models import PolicyViolation, Subscription, SubscriptionStatus, ToolResult
from .policies import (
    MAX_DISCOUNT_PERCENT, MAX_REFUND_AMOUNT, REFUND_WINDOW_DAYS,
    check_discount_cap, check_one_discount_per_customer, check_ownership,
    check_refund_cap, check_refund_window,
)
from .store import BillingStore


class BillingTools:
    TOOL_NAMES = ("get_subscription", "apply_discount", "cancel_subscription", "issue_refund")

    def __init__(self, store: BillingStore) -> None:
        self.store = store

    def execute(self, tool_name: str, /, **kwargs: Any) -> ToolResult:
        if tool_name not in self.TOOL_NAMES:
            return self._log(tool_name, self._error(tool_name, "UNKNOWN_TOOL", f"Unknown tool: {tool_name!r}"), dict(kwargs))
        handler = getattr(self, tool_name)
        try:
            inspect.signature(handler).bind(**kwargs)
        except TypeError as exc:
            return self._log(tool_name, self._error(tool_name, "INVALID_ARGUMENTS", str(exc)), dict(kwargs))
        try:
            return handler(**kwargs)
        except Exception as exc:
            return self._log(tool_name, self._error(tool_name, "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}"), dict(kwargs))

    def get_subscription(self, customer_id: str) -> ToolResult:
        tool = "get_subscription"
        args = {"customer_id": customer_id}
        customer = self.store.get_customer(customer_id)
        if customer is None:
            return self._log(tool, self._error(tool, "CUSTOMER_NOT_FOUND", f"No customer {customer_id!r}"), args)
        subs = self.store.subscriptions_for(customer_id)
        data = {"customer_id": customer.id, "customer_name": customer.name, "subscriptions": [self._sub_view(s) for s in subs]}
        return self._log(tool, ToolResult(ok=True, tool=tool, action="read", data=data, message=f"{len(subs)} subscription(s) for {customer.name}"), args)

    def apply_discount(self, sub_id: str, percent: float, actor_id: str) -> ToolResult:
        tool = "apply_discount"
        args = {"sub_id": sub_id, "percent": percent, "actor_id": actor_id}
        if not self._is_number(percent) or not 0 < percent <= 100:
            return self._log(tool, self._error(tool, "INVALID_ARGUMENT", "percent must be a number in (0, 100]"), args)
        sub = self.store.get_subscription(sub_id)
        if sub is None:
            return self._log(tool, self._error(tool, "SUBSCRIPTION_NOT_FOUND", f"No subscription {sub_id!r}"), args)
        customer = self.store.get_customer(sub.customer_id)
        if customer is None:
            return self._log(tool, self._error(tool, "INTERNAL_ERROR", f"Subscription {sub_id!r} has no customer"), args)
        violations = self._violations(check_ownership(sub, actor_id), check_discount_cap(percent), check_one_discount_per_customer(customer, sub))
        if violations:
            return self._log(tool, self._rejected(tool, violations, f"Discount of {percent:g}% rejected for {sub_id}"), args)
        sub.discount_percent = float(percent)
        customer.discount_used = True
        self.store.log_event("state_change", change="discount_applied", subscription_id=sub.id, customer_id=customer.id, percent=sub.discount_percent)
        return self._log(tool, ToolResult(ok=True, tool=tool, action="discount_applied", data={"subscription_id": sub.id, "customer_id": customer.id, "discount_percent": sub.discount_percent}, message=f"{percent:g}% discount applied to {sub.id}"), args)

    def cancel_subscription(self, sub_id: str, actor_id: str) -> ToolResult:
        tool = "cancel_subscription"
        args = {"sub_id": sub_id, "actor_id": actor_id}
        sub = self.store.get_subscription(sub_id)
        if sub is None:
            return self._log(tool, self._error(tool, "SUBSCRIPTION_NOT_FOUND", f"No subscription {sub_id!r}"), args)
        violations = self._violations(check_ownership(sub, actor_id))
        if violations:
            return self._log(tool, self._rejected(tool, violations, f"Cancellation of {sub_id} rejected"), args)
        if sub.status is SubscriptionStatus.CANCELLED:
            return self._log(tool, self._error(tool, "ALREADY_CANCELLED", f"Subscription {sub.id} is already cancelled"), args)
        sub.status = SubscriptionStatus.CANCELLED
        sub.cancelled_at = self.store.now()
        self.store.log_event("state_change", change="subscription_cancelled", subscription_id=sub.id, customer_id=sub.customer_id, cancelled_at=sub.cancelled_at.isoformat())
        return self._log(tool, ToolResult(ok=True, tool=tool, action="subscription_cancelled", data={"subscription_id": sub.id, "customer_id": sub.customer_id, "status": sub.status.value, "cancelled_at": sub.cancelled_at.isoformat()}, message=f"Subscription {sub.id} cancelled"), args)

    def issue_refund(self, sub_id: str, amount: float, actor_id: str) -> ToolResult:
        tool = "issue_refund"
        args = {"sub_id": sub_id, "amount": amount, "actor_id": actor_id}
        if not self._is_number(amount) or amount <= 0:
            return self._log(tool, self._error(tool, "INVALID_ARGUMENT", "amount must be a positive number"), args)
        sub = self.store.get_subscription(sub_id)
        if sub is None:
            return self._log(tool, self._error(tool, "SUBSCRIPTION_NOT_FOUND", f"No subscription {sub_id!r}"), args)
        now = self.store.now()
        violations = self._violations(check_ownership(sub, actor_id), check_refund_cap(amount), check_refund_window(sub, now))
        if violations:
            return self._log(tool, self._rejected(tool, violations, f"Refund of ${amount:.2f} rejected for {sub_id}"), args)
        from .models import Refund
        refund = Refund(id=self.store.next_refund_id(), subscription_id=sub.id, amount=round(float(amount), 2), actor_id=actor_id, created_at=now)
        self.store.refunds.append(refund)
        self.store.log_event("state_change", change="refund_issued", refund_id=refund.id, subscription_id=sub.id, customer_id=sub.customer_id, amount=refund.amount)
        return self._log(tool, ToolResult(ok=True, tool=tool, action="refund_issued", data=refund.model_dump(mode="json"), message=f"Refund {refund.id} of ${refund.amount:.2f} issued for {sub.id}"), args)

    @classmethod
    def tool_schemas(cls) -> list[dict[str, Any]]:
        actor = {"type": "string", "description": "ID of the customer you are acting for."}
        return [
            {"type": "function", "function": {"name": "get_subscription", "description": "Look up a customer's subscriptions.", "parameters": {"type": "object", "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"]}}},
            {"type": "function", "function": {"name": "apply_discount", "description": f"Apply a percentage discount. Max {MAX_DISCOUNT_PERCENT:g}%, one per customer.", "parameters": {"type": "object", "properties": {"sub_id": {"type": "string"}, "percent": {"type": "number"}, "actor_id": actor}, "required": ["sub_id", "percent", "actor_id"]}}},
            {"type": "function", "function": {"name": "cancel_subscription", "description": "Cancel one of the acting customer's subscriptions.", "parameters": {"type": "object", "properties": {"sub_id": {"type": "string"}, "actor_id": actor}, "required": ["sub_id", "actor_id"]}}},
            {"type": "function", "function": {"name": "issue_refund", "description": f"Refund a subscription. Max ${MAX_REFUND_AMOUNT:.2f}, within {REFUND_WINDOW_DAYS} days.", "parameters": {"type": "object", "properties": {"sub_id": {"type": "string"}, "amount": {"type": "number"}, "actor_id": actor}, "required": ["sub_id", "amount", "actor_id"]}}},
        ]

    def _sub_view(self, sub: Subscription) -> dict[str, Any]:
        plan = self.store.plans.get(sub.plan_id)
        return {
            "subscription_id": sub.id, "plan_id": sub.plan_id,
            "plan_name": plan.name if plan else None,
            "monthly_price": plan.monthly_price if plan else None,
            "status": sub.status.value, "started_at": sub.started_at.isoformat(),
            "cancelled_at": sub.cancelled_at.isoformat() if sub.cancelled_at else None,
            "discount_percent": sub.discount_percent,
            "days_since_start": (self.store.now() - sub.started_at).days,
        }

    @staticmethod
    def _violations(*checks: PolicyViolation | None) -> list[PolicyViolation]:
        return [v for v in checks if v is not None]

    @staticmethod
    def _is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))

    def _log(self, tool: str, result: ToolResult, args: dict[str, Any]) -> ToolResult:
        self.store.log_event("tool_call", tool=tool, args=args, ok=result.ok, action=result.action, violations=[v.code for v in result.violations], error_code=result.error_code)
        return result

    @staticmethod
    def _rejected(tool: str, violations: list[PolicyViolation], message: str) -> ToolResult:
        return ToolResult(ok=False, tool=tool, action="rejected", violations=violations, message=message)

    @staticmethod
    def _error(tool: str, code: str, message: str) -> ToolResult:
        return ToolResult(ok=False, tool=tool, action="error", error_code=code, message=message)
