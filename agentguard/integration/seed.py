"""Build a billing store from a simulator scenario's seed (contract v2 section 5)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Callable

from ..backend.models import Customer, Plan, Subscription, SubscriptionStatus
from ..backend.store import BillingStore
from ..simulator.scenarios import Scenario

FIXED_NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def fixed_clock() -> Callable[[], datetime]:
    """The store clock: 2026-10-22T12:00:00Z, or ``AGENTGUARD_NOW`` (ISO 8601) if set."""
    override = os.environ.get("AGENTGUARD_NOW")
    now = datetime.fromisoformat(override.replace("Z", "+00:00")) if override else FIXED_NOW
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return lambda: now


def subscription_id(customer_id: str) -> str:
    return f"SUB-{customer_id}"


def plan_id(plan: str) -> str:
    return f"PLAN-{plan.upper()}"


def _day(date: str) -> datetime:
    return datetime.fromisoformat(date).replace(tzinfo=timezone.utc)


def build_store_from_scenario(scenario: Scenario, clock: Callable[[], datetime] | None = None) -> BillingStore:
    store = BillingStore(clock=clock or fixed_clock())
    for customer_id, record in scenario.seed.items():
        store.customers[customer_id] = Customer(
            id=customer_id,
            name=record["name"],
            email=f"{customer_id.lower()}@example.com",
            discount_used=record.get("discount_percent", 0) > 0,
        )
        pid = plan_id(record["plan"])
        store.plans.setdefault(pid, Plan(id=pid, name=record["plan"], monthly_price=record["monthly_price"]))
        payments = sorted(record.get("payments", []), key=lambda p: p["date"])
        started = _day(payments[0]["date"]) if payments else store.now()
        last = payments[-1] if payments else None
        sid = subscription_id(customer_id)
        store.subscriptions[sid] = Subscription(
            id=sid,
            customer_id=customer_id,
            plan_id=pid,
            status=SubscriptionStatus(record.get("status", "active")),
            started_at=started,
            discount_percent=float(record.get("discount_percent", 0)),
            last_charged_at=_day(last["date"]) if last else None,
            last_charge_amount=float(last["amount"]) if last else None,
        )
    store.log_event("seed", scenario_id=scenario.id, customers=len(store.customers))
    return store
