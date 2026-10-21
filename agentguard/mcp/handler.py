"""The handler: policy engine in front of every tool call.

This is the testable core — no MCP transport, no asyncio, no stdio.
The MCP server wires this handler to the protocol.

Contract:
  handle(tool_name, arguments, session_id) -> dict (success payload)
  raises ToolBlocked if policy engine returns BLOCKED.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentguard.policy.cumulative import SessionState
from agentguard.policy.engine import PolicyEngine
from agentguard.policy.schema import ToolCallEvent

logger = logging.getLogger(__name__)

DEFAULT_POLICY_FILE = (
    Path(__file__).parent.parent / "policy" / "policies" / "stripe.yaml"
)


class ToolBlocked(Exception):
    """Raised when the policy engine blocks a tool call."""

    def __init__(self, violated_policy: str, detail: str) -> None:
        self.violated_policy = violated_policy
        self.detail = detail
        super().__init__(f"[{violated_policy}] {detail}")


class BillingHandler:
    def __init__(self, policy_file: str | Path = DEFAULT_POLICY_FILE) -> None:
        self.engine = PolicyEngine.from_yaml(policy_file)
        self._sessions: dict[str, SessionState] = {}

    def _state_for(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState()
        return self._sessions[session_id]

    def handle(
        self, tool_name: str, arguments: dict[str, Any], session_id: str
    ) -> dict[str, Any]:
        event = ToolCallEvent(
            session_id=session_id,
            tool_name=tool_name,
            arguments=arguments,
            timestamp=datetime.now(timezone.utc),
        )
        state = self._state_for(session_id)
        result = self.engine.evaluate(event, state)

        if result.status == "BLOCKED":
            logger.warning(
                "blocked %s session=%s policy=%s",
                tool_name,
                session_id,
                result.violated_policy,
            )
            raise ToolBlocked(
                result.violated_policy or "unknown",
                result.detail or "Policy violation",
            )

        logger.info("allowed %s session=%s", tool_name, session_id)
        return {
            "status": "ALLOWED",
            "tool": tool_name,
            "arguments": arguments,
            "session_id": session_id,
        }
