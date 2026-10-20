"""In-memory billing state plus an append-only event log."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from .models import Customer, Plan, Refund, Subscription


class BillingStore:
    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.customers: dict[str, Customer] = {}
        self.plans: dict[str, Plan] = {}
        self.subscriptions: dict[str, Subscription] = {}
        self.refunds: list[Refund] = []
        self.events: list[dict[str, Any]] = []

    def now(self) -> datetime:
        return self._clock()

    def get_customer(self, customer_id: str) -> Customer | None:
        return self.customers.get(customer_id)

    def get_subscription(self, sub_id: str) -> Subscription | None:
        return self.subscriptions.get(sub_id)

    def subscriptions_for(self, customer_id: str) -> list[Subscription]:
        return sorted(
            (s for s in self.subscriptions.values() if s.customer_id == customer_id),
            key=lambda s: s.id,
        )

    def next_refund_id(self) -> str:
        return f"RFD-{len(self.refunds) + 1:04d}"

    def log_event(self, event_type: str, **payload: Any) -> None:
        self.events.append({"ts": self.now().isoformat(), "type": event_type, **payload})

    def snapshot(self) -> dict[str, Any]:
        return {
            "taken_at": self.now().isoformat(),
            "customers": {cid: c.model_dump(mode="json") for cid, c in self.customers.items()},
            "subscriptions": {sid: s.model_dump(mode="json") for sid, s in self.subscriptions.items()},
            "refunds": [r.model_dump(mode="json") for r in self.refunds],
            "events": list(self.events),
        }
