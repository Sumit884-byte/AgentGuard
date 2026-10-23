"""The five billing policies, as ordinary Python."""
from __future__ import annotations

from datetime import datetime, timedelta

from .models import Customer, PolicyViolation, Subscription

MAX_DISCOUNT_PERCENT = 20.0
MAX_REFUND_AMOUNT = 50.0
REFUND_WINDOW_DAYS = 30


def check_discount_cap(percent: float) -> PolicyViolation | None:
    if percent > MAX_DISCOUNT_PERCENT:
        return PolicyViolation(
            code="DISCOUNT_CAP_EXCEEDED",
            policy="max_discount_20pct",
            detail=f"Requested discount {percent:g}% exceeds the {MAX_DISCOUNT_PERCENT:g}% maximum",
        )
    return None


def check_refund_cap(amount: float) -> PolicyViolation | None:
    if amount > MAX_REFUND_AMOUNT:
        return PolicyViolation(
            code="REFUND_CAP_EXCEEDED",
            policy="max_refund_50_usd",
            detail=f"Requested refund ${amount:.2f} exceeds the ${MAX_REFUND_AMOUNT:.2f} maximum",
        )
    return None


def check_ownership(sub: Subscription, actor_id: str) -> PolicyViolation | None:
    if sub.customer_id != actor_id:
        return PolicyViolation(
            code="NOT_SUBSCRIPTION_OWNER",
            policy="own_subscription_only",
            detail=f"Subscription {sub.id} belongs to {sub.customer_id}, but the request was made for {actor_id}",
        )
    return None


def charge_date(sub: Subscription) -> datetime:
    """The charge a refund applies to: the latest charge, or the start date when unknown (v1 seed)."""
    return sub.last_charged_at or sub.started_at


def check_refund_window(sub: Subscription, now: datetime) -> PolicyViolation | None:
    age = now - charge_date(sub)
    if age > timedelta(days=REFUND_WINDOW_DAYS):
        return PolicyViolation(
            code="REFUND_WINDOW_EXPIRED",
            policy="refund_window_30_days",
            detail=f"Subscription {sub.id} was last charged {age.days} days ago; refunds are only allowed within {REFUND_WINDOW_DAYS} days",
        )
    return None


def check_one_discount_per_customer(customer: Customer, sub: Subscription) -> PolicyViolation | None:
    if customer.discount_used or sub.discount_percent > 0:
        return PolicyViolation(
            code="DISCOUNT_ALREADY_USED",
            policy="one_discount_per_customer",
            detail=f"Customer {customer.id} has already received a discount",
        )
    return None
