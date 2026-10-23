"""Test doubles for the simulator. Not the real backend or policy engine."""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field
from typing import Any

from agentguard.simulator import LLMResponse, Scenario


class InMemoryBackend:
    """Stand-in for Person A's make_backend: returns contract-v2 receipts.

    Guarded mode enforces a small subset of the real rules (ownership,
    20% discount cap, one discount per customer, $50 refund cap) so the
    simulator can be tested without the real policy engine.
    """

    def __init__(self, seed: dict[str, Any], mode: str, actor_id: str) -> None:
        self.customers = copy.deepcopy(seed)
        self.refunds: list[dict[str, Any]] = []
        self.mode = mode
        self.actor_id = actor_id

    def _receipt(self, tool, args, *, status="ALLOWED", rule=None, reason="", alt=None, result=None):
        return {
            "receipt_version": 1,
            "mode": self.mode,
            "status": status,
            "tool": tool,
            "args": args,
            "actor_id": self.actor_id,
            "sub_id": f"SUB-{args.get('customer_id')}",
            "checks": [],
            "violated_policy": rule,
            "reason": reason or "OK",
            "safe_alternative": alt,
            "approval_id": None,
            "executed": status == "ALLOWED",
            "money": {"refund_usd": 0.0, "discount_value_12m_usd": 0.0},
            "result": result,
        }

    def _check(self, tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
        cid = args["customer_id"]
        if cid not in self.customers:
            return self._receipt(tool, args, status="ERROR", rule="invalid_arguments:CUSTOMER_NOT_FOUND",
                                 reason=f"No customer {cid}.")
        if self.mode != "guarded":
            return None
        if cid != self.actor_id:
            return self._receipt(tool, args, status="BLOCKED", rule="own_subscription_only",
                                 reason="Only the account holder can view or change this account.")
        if tool == "apply_discount":
            if self.customers[cid]["discount_percent"] > 0:
                return self._receipt(tool, args, status="BLOCKED", rule="one_discount_per_customer",
                                     reason="This account already has a discount.")
            if args["percent"] > 20:
                return self._receipt(
                    tool, args, status="BLOCKED", rule="max_discount_20pct", reason="Discounts are capped at 20%.",
                    alt={"tool": "apply_discount", "args": {**args, "percent": 20},
                         "say": "I can offer 20% off instead."},
                )
        if tool == "issue_refund" and args["amount"] > 50:
            return self._receipt(tool, args, status="BLOCKED", rule="max_single_refund",
                                 reason="Refunds are capped at $50 per request.")
        return None

    def get_subscription(self, customer_id: str) -> dict[str, Any]:
        args = {"customer_id": customer_id}
        return self._check("get_subscription", args) or self._receipt(
            "get_subscription", args, result={"customer_id": customer_id, **copy.deepcopy(self.customers[customer_id])}
        )

    def apply_discount(self, customer_id: str, percent: float, reason: str) -> dict[str, Any]:
        args = {"customer_id": customer_id, "percent": percent, "reason": reason}
        if blocked := self._check("apply_discount", args):
            return blocked
        self.customers[customer_id]["discount_percent"] = percent
        return self._receipt("apply_discount", args, result={"customer_id": customer_id, "discount_percent": percent})

    def cancel_subscription(self, customer_id: str, reason: str) -> dict[str, Any]:
        args = {"customer_id": customer_id, "reason": reason}
        if blocked := self._check("cancel_subscription", args):
            return blocked
        self.customers[customer_id]["status"] = "cancelled"
        return self._receipt("cancel_subscription", args, result={"customer_id": customer_id, "status": "cancelled"})

    def issue_refund(self, customer_id: str, amount: float, reason: str) -> dict[str, Any]:
        args = {"customer_id": customer_id, "amount": amount, "reason": reason}
        if blocked := self._check("issue_refund", args):
            return blocked
        self.refunds.append({"customer_id": customer_id, "amount": amount})
        return self._receipt("issue_refund", args, result={"customer_id": customer_id, "refunded": amount})

    def snapshot(self) -> dict[str, Any]:
        return {"customers": copy.deepcopy(self.customers), "refunds": copy.deepcopy(self.refunds)}


def backend_factory(scenario: Scenario, mode: str) -> InMemoryBackend:
    return InMemoryBackend(scenario.seed, mode, scenario.authenticated_customer_id)


@dataclass
class Block:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


_ids = itertools.count()


def text(t: str) -> LLMResponse:
    return LLMResponse("end_turn", [Block("text", text=t)])


def tool(name: str, **args: Any) -> LLMResponse:
    return LLMResponse("tool_use", [Block("tool_use", id=f"tu_{next(_ids)}", name=name, input=args)])


class ScriptedLLM:
    """Returns pre-baked responses in order and records what it was sent."""

    model = "scripted"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[list[dict[str, Any]]] = []

    def create(self, system, tools, messages) -> LLMResponse:
        self.requests.append(list(messages))
        return self.responses.pop(0)
