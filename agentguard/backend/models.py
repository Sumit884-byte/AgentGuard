"""Pydantic models shared by the billing backend, simulator, and evaluator."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"


class Customer(BaseModel):
    id: str
    name: str
    email: str
    discount_used: bool = False


class Plan(BaseModel):
    id: str
    name: str
    monthly_price: float


class Subscription(BaseModel):
    id: str
    customer_id: str
    plan_id: str
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    started_at: datetime
    cancelled_at: datetime | None = None
    discount_percent: float = 0.0


class Refund(BaseModel):
    id: str
    subscription_id: str
    amount: float
    actor_id: str
    created_at: datetime


class PolicyViolation(BaseModel):
    code: str
    policy: str
    detail: str


class ToolResult(BaseModel):
    ok: bool
    tool: str
    action: str
    data: dict[str, Any] | None = None
    violations: list[PolicyViolation] = Field(default_factory=list)
    error_code: str | None = None
    message: str = ""
