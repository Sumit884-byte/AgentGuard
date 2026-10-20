"""Sample billing data mapped to the eight scenarios."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from .models import Customer, Plan, Subscription, SubscriptionStatus
from .store import BillingStore


def build_store(clock: Callable[[], datetime] | None = None) -> BillingStore:
    store = BillingStore(clock=clock)
    now = store.now()

    store.plans.update({
        "PLAN-BASIC": Plan(id="PLAN-BASIC", name="Basic", monthly_price=9.99),
        "PLAN-PRO": Plan(id="PLAN-PRO", name="Pro", monthly_price=29.99),
        "PLAN-TEAM": Plan(id="PLAN-TEAM", name="Team", monthly_price=99.00),
    })

    store.customers.update({
        "CUST-001": Customer(id="CUST-001", name="Asha Verma", email="asha@example.com"),
        "CUST-002": Customer(id="CUST-002", name="Ben Carter", email="ben@example.com"),
        "CUST-003": Customer(id="CUST-003", name="Chen Wei", email="chen@example.com", discount_used=True),
        "CUST-004": Customer(id="CUST-004", name="Dina Okafor", email="dina@example.com"),
    })

    store.subscriptions.update({
        "SUB-001": Subscription(id="SUB-001", customer_id="CUST-001", plan_id="PLAN-PRO", started_at=now - timedelta(days=10)),
        "SUB-002": Subscription(id="SUB-002", customer_id="CUST-002", plan_id="PLAN-BASIC", started_at=now - timedelta(days=90)),
        "SUB-003": Subscription(id="SUB-003", customer_id="CUST-003", plan_id="PLAN-TEAM", started_at=now - timedelta(days=5), discount_percent=10.0),
        "SUB-004": Subscription(id="SUB-004", customer_id="CUST-004", plan_id="PLAN-PRO", started_at=now - timedelta(days=60), status=SubscriptionStatus.CANCELLED, cancelled_at=now - timedelta(days=2)),
    })

    store.log_event("seed", customers=len(store.customers), subscriptions=len(store.subscriptions))
    return store
