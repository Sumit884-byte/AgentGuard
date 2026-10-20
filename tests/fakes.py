"""Test doubles for the simulator. Not the real backend or policy engine."""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field
from typing import Any

from agentguard.simulator import LLMResponse, Scenario


class InMemoryBackend:
    def __init__(self, seed: dict[str, Any]) -> None:
        self.customers = copy.deepcopy(seed)
        self.refunds: list[dict[str, Any]] = []

    def _get(self, customer_id: str) -> dict[str, Any]:
        if customer_id not in self.customers:
            raise KeyError(f"unknown customer {customer_id}")
        return self.customers[customer_id]

    def get_subscription(self, customer_id: str) -> dict[str, Any]:
        return {"customer_id": customer_id, **copy.deepcopy(self._get(customer_id))}

    def apply_discount(self, customer_id: str, percent: float, reason: str) -> dict[str, Any]:
        self._get(customer_id)["discount_percent"] = percent
        return {"customer_id": customer_id, "discount_percent": percent}

    def cancel_subscription(self, customer_id: str, reason: str) -> dict[str, Any]:
        self._get(customer_id)["status"] = "cancelled"
        return {"customer_id": customer_id, "status": "cancelled"}

    def issue_refund(self, customer_id: str, amount: float, reason: str) -> dict[str, Any]:
        self._get(customer_id)
        self.refunds.append({"customer_id": customer_id, "amount": amount})
        return {"customer_id": customer_id, "refunded": amount}

    def snapshot(self) -> dict[str, Any]:
        return {"customers": copy.deepcopy(self.customers), "refunds": copy.deepcopy(self.refunds)}


def backend_factory(scenario: Scenario) -> InMemoryBackend:
    return InMemoryBackend(scenario.seed)


@dataclass
class Decision:
    allowed: bool
    reason: str = ""


class CapPolicy:
    """Toy policy: discounts capped at 20%, only the authenticated account."""

    def check(self, tool_name, arguments, context, backend) -> Decision:
        if arguments.get("customer_id") != context["authenticated_customer_id"]:
            return Decision(False, "account_ownership")
        if tool_name == "apply_discount" and arguments["percent"] > 20:
            return Decision(False, "max_discount")
        return Decision(True)


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
