"""Cumulative session state — keyed by sub_id, persists across sessions.

Security model:
- Cumulative state is keyed by sub_id, not session_id.
  A hostile agent cannot evade the cap by changing its session ID.
- The session_id field is kept for logging only; it does not partition state.
- The handler overwrites days_since_charge from authoritative store data
  before YAML eval, so client misreporting is ignored.
"""
from __future__ import annotations

from datetime import datetime

from .schema import ToolCallEvent


class SessionState:
    """Process-wide cumulative state. One instance per handler."""

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.refunds_by_charge: dict[str, float] = {}
        self.last_seen: datetime | None = None

    def refunds_today_on_charge(self, sub_id: str) -> float:
        return self.refunds_by_charge.get(sub_id, 0.0)

    def record_refund(self, sub_id: str, amount: float) -> None:
        self.refunds_by_charge[sub_id] = self.refunds_by_charge.get(sub_id, 0.0) + amount

    def _sub_key(self, event: ToolCallEvent) -> str:
        return event.arguments.get("sub_id") or event.arguments.get("charge_id", "")

    def build_context(self, event: ToolCallEvent) -> dict:
        # Track session_id for logging only — no state reset.
        self.session_id = event.session_id
        ctx = dict(event.arguments)
        ctx["refunds_today_on_charge"] = self.refunds_today_on_charge(self._sub_key(event))
        ctx.setdefault("days_since_charge", 0)
        return ctx

    def apply_mutation(self, event: ToolCallEvent) -> None:
        self.session_id = event.session_id
        if event.tool_name == "issue_refund":
            self.record_refund(self._sub_key(event), float(event.arguments.get("amount", 0.0)))
        self.last_seen = event.timestamp
