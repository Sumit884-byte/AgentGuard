"""In-process backend adapter: ``make_backend(scenario, mode)`` (contract v2 sections 2 to 4).

Wraps the billing store, the YAML policy engine and the backend policies, and
returns a decision receipt for every call. Never raises for policy or argument
problems.

- naive: argument validation and state changes only; ``checks`` is empty.
- guarded: ownership first (handler layer), then every YAML rule, then the
  backend policies. ``violated_policy`` is the first failure in that order;
  state changes only if every check passes.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from ..backend.models import Customer, Subscription, SubscriptionStatus
from ..backend.policies import (
    MAX_DISCOUNT_PERCENT, MAX_REFUND_AMOUNT, REFUND_WINDOW_DAYS, charge_date,
    check_discount_cap, check_one_discount_per_customer, check_refund_cap, check_refund_window,
)
from ..backend.tools import BillingTools
from ..mcp.handler import DEFAULT_POLICY_FILE
from ..policy.cumulative import SessionState
from ..policy.engine import PolicyEngine
from ..policy.schema import ToolCallEvent
from ..simulator.scenarios import Scenario
from .seed import build_store_from_scenario, subscription_id

Mode = Literal["naive", "guarded"]

REASONS = {
    "own_subscription_only": "Only the account holder can view or change this account.",
    "max_single_refund": f"Refunds are capped at ${MAX_REFUND_AMOUNT:.0f} per request.",
    "max_daily_refund_cap": f"Refunds on one charge are capped at ${MAX_REFUND_AMOUNT:.0f} in total.",
    "max_refund_50_usd": f"Refunds are capped at ${MAX_REFUND_AMOUNT:.0f} per request.",
    "refund_requires_reason": "Every refund needs a reason of at least 5 characters.",
    "no_refund_after_30_days": f"Only charges from the last {REFUND_WINDOW_DAYS} days can be refunded.",
    "refund_window_30_days": f"Only charges from the last {REFUND_WINDOW_DAYS} days can be refunded.",
    "max_discount_20pct": f"Discounts are capped at {MAX_DISCOUNT_PERCENT:.0f}%.",
    "one_discount_per_customer": "This account already has a discount, and only one is allowed.",
}
REFUND_CAP_RULES = {"max_single_refund", "max_daily_refund_cap", "max_refund_50_usd"}
WINDOW_RULES = {"no_refund_after_30_days", "refund_window_30_days"}
DISCOUNT_CAP_RULES = {"max_discount_20pct"}


def make_backend(scenario: Scenario, mode: Mode) -> "Backend":
    """Fresh store, policy engine and cumulative state for one run."""
    return Backend(scenario, mode)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _check(rule: str, layer: str, passed: bool, values: dict[str, Any], detail: str = "") -> dict[str, Any]:
    return {"rule": rule, "layer": layer, "passed": passed, "values": values, "detail": "" if passed else detail}


class Backend:
    def __init__(self, scenario: Scenario, mode: Mode, policy_file: Any = DEFAULT_POLICY_FILE) -> None:
        if mode not in ("naive", "guarded"):
            raise ValueError(f"mode must be 'naive' or 'guarded', got {mode!r}")
        self.scenario = scenario
        self.mode = mode
        self.actor_id = scenario.authenticated_customer_id
        self.store = build_store_from_scenario(scenario)
        self.tools = BillingTools(self.store, enforce_policies=(mode == "guarded"))
        self.engine = PolicyEngine.from_yaml(policy_file)
        self.state = SessionState()

    # ------------------------------------------------------------ model-facing tools

    def get_subscription(self, customer_id: str) -> dict[str, Any]:
        return self._call("get_subscription", {"customer_id": customer_id})

    def apply_discount(self, customer_id: str, percent: float, reason: str) -> dict[str, Any]:
        return self._call("apply_discount", {"customer_id": customer_id, "percent": percent, "reason": reason})

    def cancel_subscription(self, customer_id: str, reason: str) -> dict[str, Any]:
        return self._call("cancel_subscription", {"customer_id": customer_id, "reason": reason})

    def issue_refund(self, customer_id: str, amount: float, reason: str) -> dict[str, Any]:
        return self._call("issue_refund", {"customer_id": customer_id, "amount": amount, "reason": reason})

    def snapshot(self) -> dict[str, Any]:
        return self.store.snapshot()

    # ------------------------------------------------------------ one call

    def _call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        args = {k: float(v) if k in ("amount", "percent") and _is_number(v) else v for k, v in args.items()}
        receipt = self._receipt(tool, args)

        error = self._validate(tool, args)
        if error:
            code, reason = error
            receipt["sub_id"] = None if code == "CUSTOMER_NOT_FOUND" else receipt["sub_id"]
            return {**receipt, "status": "ERROR", "violated_policy": f"invalid_arguments:{code}", "reason": reason}

        sub = self.store.subscriptions[receipt["sub_id"]]
        customer = self.store.customers[sub.customer_id]
        if self.mode == "guarded":
            receipt["checks"] = self._checks(tool, args, sub, customer)
            failed = [c["rule"] for c in receipt["checks"] if not c["passed"]]
            if failed:
                return {
                    **receipt,
                    "status": "BLOCKED",
                    "violated_policy": failed[0],
                    "reason": REASONS.get(failed[0]) or next(c["detail"] for c in receipt["checks"] if not c["passed"]),
                    "safe_alternative": self._safe_alternative(set(failed), args, sub, customer),
                }

        old_discount = sub.discount_percent
        tool_args = {"customer_id": args["customer_id"]} if tool == "get_subscription" else {
            "sub_id": sub.id, "actor_id": self.actor_id,
            **({"percent": args["percent"]} if tool == "apply_discount" else {}),
            **({"amount": args["amount"]} if tool == "issue_refund" else {}),
        }
        result = self.tools.execute(tool, **tool_args)
        if not result.ok:  # defense in depth: the tool layer disagreed with the checks above
            if result.violations:
                first = result.violations[0]
                return {**receipt, "status": "BLOCKED", "violated_policy": first.policy,
                        "reason": REASONS.get(first.policy, first.detail)}
            return {**receipt, "status": "ERROR", "violated_policy": f"invalid_arguments:{result.error_code}",
                    "reason": result.message or "The request could not be completed."}

        if tool == "issue_refund" and self.mode == "guarded":
            self.state.record_refund(sub.id, args["amount"])
        return {**receipt, "status": "ALLOWED", "reason": "Allowed.", "executed": True,
                "money": self._money(tool, args, sub, old_discount), "result": result.model_dump(mode="json")}

    # ------------------------------------------------------------ pieces

    def _receipt(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        customer_id = args.get("customer_id")
        return {
            "receipt_version": 1, "mode": self.mode, "status": None, "tool": tool, "args": args,
            "actor_id": self.actor_id,
            "sub_id": subscription_id(customer_id) if isinstance(customer_id, str) else None,
            "checks": [], "violated_policy": None, "reason": "", "safe_alternative": None,
            "approval_id": None, "executed": False,
            "money": {"refund_usd": 0.0, "discount_value_12m_usd": 0.0}, "result": None,
        }

    def _validate(self, tool: str, args: dict[str, Any]) -> tuple[str, str] | None:
        customer_id = args.get("customer_id")
        if not isinstance(customer_id, str) or self.store.get_customer(customer_id) is None:
            return "CUSTOMER_NOT_FOUND", f"There is no customer {customer_id}."
        if subscription_id(customer_id) not in self.store.subscriptions:
            return "SUBSCRIPTION_NOT_FOUND", f"Customer {customer_id} has no subscription."
        if "reason" in args and not isinstance(args["reason"], str):
            return "INVALID_ARGUMENT", "The reason must be text."
        if tool == "apply_discount" and not (_is_number(args["percent"]) and 0 < args["percent"] <= 100):
            return "INVALID_ARGUMENT", "The discount must be a number above 0 and at most 100."
        if tool == "issue_refund" and not (_is_number(args["amount"]) and args["amount"] > 0):
            return "INVALID_ARGUMENT", "The refund amount must be a positive number."
        sub = self.store.subscriptions[subscription_id(customer_id)]
        if tool == "cancel_subscription" and sub.status is SubscriptionStatus.CANCELLED:
            return "ALREADY_CANCELLED", "This subscription is already cancelled."
        return None

    def _checks(self, tool: str, args: dict[str, Any], sub: Subscription, customer: Customer) -> list[dict]:
        owner_ok = sub.customer_id == self.actor_id
        checks = [_check("own_subscription_only", "handler", owner_ok,
                         {"owner": sub.customer_id, "actor": self.actor_id},
                         f"{sub.id} belongs to {sub.customer_id}, not {self.actor_id}")]

        now = self.store.now()
        days_since_charge = (now - charge_date(sub)).days
        event = ToolCallEvent(
            session_id=self.scenario.id, tool_name=tool, timestamp=now,
            arguments={**{k: v for k, v in args.items() if k != "customer_id"},
                       "sub_id": sub.id, "days_since_charge": days_since_charge},
        )
        for rule, passed, detail, values in self.engine.evaluate_all(event, self.state):
            checks.append(_check(rule.name, "yaml", passed, values, detail))

        backend: list[tuple[str, Any, dict[str, Any]]] = []
        if tool == "apply_discount":
            backend = [
                ("max_discount_20pct", check_discount_cap(args["percent"]),
                 {"percent": args["percent"], "limit": MAX_DISCOUNT_PERCENT}),
                ("one_discount_per_customer", check_one_discount_per_customer(customer, sub),
                 {"discount_used": customer.discount_used, "current_discount_percent": sub.discount_percent}),
            ]
        elif tool == "issue_refund":
            backend = [
                ("max_refund_50_usd", check_refund_cap(args["amount"]),
                 {"amount": args["amount"], "limit": MAX_REFUND_AMOUNT}),
                ("refund_window_30_days", check_refund_window(sub, now),
                 {"days_since_charge": days_since_charge, "limit": REFUND_WINDOW_DAYS}),
            ]
        for name, violation, values in backend:
            checks.append(_check(name, "backend", violation is None, values, violation.detail if violation else ""))
        return checks

    def _safe_alternative(self, failed: set[str], args: dict[str, Any], sub: Subscription,
                          customer: Customer) -> dict[str, Any] | None:
        """Contract v2 section 4: first matching rule wins."""
        customer_id = args["customer_id"]
        if "own_subscription_only" in failed:
            return None
        if failed & WINDOW_RULES and sub.status is SubscriptionStatus.ACTIVE:
            return {
                "tool": "cancel_subscription",
                "args": {"customer_id": customer_id, "reason": "Refund requested outside the 30-day window"},
                "say": "I can't refund a charge from more than 30 days ago, but I can cancel your subscription "
                       "so you aren't charged again.",
            }
        if failed & REFUND_CAP_RULES:
            remaining = MAX_REFUND_AMOUNT - self.state.refunds_today_on_charge(sub.id)
            amount = round(min(remaining, sub.last_charge_amount or MAX_REFUND_AMOUNT), 2)
            if amount <= 0:
                return None
            whole = sub.last_charge_amount is not None and amount == round(sub.last_charge_amount, 2)
            return {
                "tool": "issue_refund",
                "args": {"customer_id": customer_id, "amount": amount, "reason": "Refund of last charge"},
                "say": f"I can refund your last charge of ${amount:.2f} right now." if whole
                       else f"I can refund ${amount:.2f} right now.",
            }
        if failed & DISCOUNT_CAP_RULES and not customer.discount_used and sub.discount_percent == 0:
            return {
                "tool": "apply_discount",
                "args": {"customer_id": customer_id, "percent": MAX_DISCOUNT_PERCENT, "reason": args.get("reason", "")},
                "say": f"I can offer {MAX_DISCOUNT_PERCENT:.0f}% off instead.",
            }
        return None

    def _money(self, tool: str, args: dict[str, Any], sub: Subscription, old_discount: float) -> dict[str, float]:
        refund = args["amount"] if tool == "issue_refund" else 0.0
        discount = 0.0
        if tool == "apply_discount" and sub.status is SubscriptionStatus.ACTIVE:
            price = self.store.plans[sub.plan_id].monthly_price
            discount = price * max(0.0, sub.discount_percent - old_discount) / 100 * 12
        return {"refund_usd": round(refund, 2), "discount_value_12m_usd": round(discount, 2)}
