"""Frozen schema models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCallEvent(BaseModel):
    """Frozen schema #1 — Eng1 <-> Eng2 interface."""
    session_id: str
    tool_name: str
    arguments: dict[str, Any]
    timestamp: datetime


class PolicyResult(BaseModel):
    status: Literal["ALLOWED", "BLOCKED"]
    violated_policy: str | None = None
    detail: str = ""


class PolicyRule(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    applies_to: list[str] = Field(min_length=1)
    condition: str = Field(min_length=1)
    violation_detail: str = ""
    description: str = ""
