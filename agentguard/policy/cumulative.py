"""Cumulative session state — the thing per-call checks miss.

The exploit this exists for (from the frozen trace fixture):
  3 separate $30 refunds on one charge = $90 total.
  Per-call check sees each $30 <= $50 → all pass.
  Cumulative check sees 30 + 30 = 60 > 50 → call 2 blocked.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .schema import ToolCallEvent


class SessionState:
    """Tracks cumulative state per session. One instance = one session."""

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.refunds_by_charge: dict[str, float] = {}
        self.last_seen: datetime | None = None

    def _ensure_session(self, event: ToolCallEvent) -> None:
        """Reset state when session_id changes — sessions are isolated."""
        if self.session_id != event.session_id:
            self.session_id = event.session_id
            self.refunds_by_charge.clear()

    def refunds_today_on_charge(self, charge_id: str) -> float:
        return self.refunds_by_charge.get(charge_id, 0.0)

    def record_refund(self, charge_id: str, amount: float) -> None:
        self.refunds_by_charge[charge_id] = (
            self.refunds_by_charge.get(charge_id, 0.0) + amount
        )

    def build_context(self, event: ToolCallEvent) -> dict:
        """The variables available to YAML rule conditions.

        Merges tool arguments with derived cumulative state.
        If a tool argument and a derived variable share a name,
        the derived one wins (that's the whole point of cumulative).
        """
        self._ensure_session(event)
        ctx = dict(event.arguments)

        charge_id = event.arguments.get("charge_id", "")
        ctx["refunds_today_on_charge"] = self.refunds_today_on_charge(charge_id)

        # days_since_charge: computed from arguments if caller supplies
        # the original charge timestamp (Eng2's job to supply it).
        charge_ts = event.arguments.get("charge_timestamp")
        if isinstance(charge_ts, str):
            try:
                started = datetime.fromisoformat(charge_ts.replace("Z", "+00:00"))
                delta = event.timestamp - started
                ctx["days_since_charge"] = delta.days
            except ValueError:
                ctx["days_since_charge"] = 0
        else:
            ctx["days_since_charge"] = event.arguments.get("days_since_charge", 0)

        return ctx

    def apply_mutation(self, event: ToolCallEvent) -> None:
        """Only called AFTER a call is ALLOWED. Never on BLOCKED."""
        self._ensure_session(event)
        if event.tool_name == "issue_refund":
            charge_id = event.arguments.get("charge_id", "")
            amount = float(event.arguments.get("amount", 0.0))
            self.record_refund(charge_id, amount)
        self.last_seen = event.timestamp
