"""The handler: YAML policy + BillingTools, in that order.

Every call goes through two independent checks:
  1. YAML policy engine (cumulative caps, reason, window, negative amounts)
  2. BillingTools.execute() (ownership, amount, window, actual mutation)

Both must pass. Cumulative state is process-wide, NOT per-session —
a hostile agent cannot reset it by changing session_id.

Authoritative data wins:
  - days_since_charge is overwritten from sub.started_at; client value ignored.
  - actor_id flows through to BillingTools.check_ownership().

Args reaching BillingTools are filtered to its accepted signature — YAML-only
fields (reason, days_since_charge) stay out of the tool layer.
"""
from __future__ import annotations

import inspect
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentguard.backend.policies import charge_date
from agentguard.backend.seed import build_store
from agentguard.backend.tools import BillingTools
from agentguard.policy.cumulative import SessionState
from agentguard.policy.engine import PolicyEngine
from agentguard.policy.schema import ToolCallEvent

logger = logging.getLogger(__name__)

DEFAULT_POLICY_FILE = (
    Path(__file__).parent.parent / "policy" / "policies" / "stripe.yaml"
)


class ToolBlocked(Exception):
    """Raised when either YAML policy or BillingTools blocks a call."""

    def __init__(self, violated_policy: str, detail: str) -> None:
        self.violated_policy = violated_policy
        self.detail = detail
        super().__init__(f"[{violated_policy}] {detail}")


class BillingHandler:
    def __init__(
        self,
        policy_file: str | Path = DEFAULT_POLICY_FILE,
        billing: BillingTools | None = None,
    ) -> None:
        self.engine = PolicyEngine.from_yaml(policy_file)
        self.billing = billing or BillingTools(build_store())
        # Single process-wide cumulative state. Not per-session.
        self.state = SessionState()

    def _billing_args(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Filter args to what BillingTools.<tool_name> actually accepts."""
        method = getattr(self.billing, tool_name, None)
        if method is None:
            return {}
        accepted = set(inspect.signature(method).parameters.keys())
        return {k: v for k, v in args.items() if k in accepted}

    def handle(
        self, tool_name: str, arguments: dict[str, Any], session_id: str
    ) -> dict[str, Any]:
        # Normalize charge_id -> sub_id (MCP uses charge_id; BillingTools uses sub_id).
        args = dict(arguments)
        if "charge_id" in args and "sub_id" not in args:
            args["sub_id"] = args.pop("charge_id")
        if "subscription_id" in args and "sub_id" not in args:
            args["sub_id"] = args.pop("subscription_id")

        # Overwrite client-supplied days_since_charge with authoritative store data.
        if tool_name == "issue_refund" and "sub_id" in args:
            sub = self.billing.store.get_subscription(args["sub_id"])
            if sub is not None:
                args["days_since_charge"] = (
                    self.billing.store.now() - charge_date(sub)
                ).days

        # Layer 1: YAML policy (cumulative + reason + window + negative amount).
        event = ToolCallEvent(
            session_id=session_id,
            tool_name=tool_name,
            arguments=args,
            timestamp=datetime.now(timezone.utc),
        )
        yaml_result = self.engine.evaluate(event, self.state)
        if yaml_result.status == "BLOCKED":
            logger.warning(
                "yaml_blocked tool=%s session=%s policy=%s",
                tool_name, session_id, yaml_result.violated_policy,
            )
            raise ToolBlocked(
                yaml_result.violated_policy or "unknown",
                yaml_result.detail or "YAML policy violation",
            )

        # Layer 2: BillingTools execution (ownership + mutation + final cap).
        # Only pass args BillingTools accepts — YAML-only fields (reason,
        # days_since_charge) must not leak into the tool layer.
        billing_args = self._billing_args(tool_name, args)
        tool_result = self.billing.execute(tool_name, **billing_args)
        if not tool_result.ok:
            # Defense-in-depth: if YAML accepted but BillingTools rejected,
            # undo the cumulative mutation the engine applied on ALLOWED.
            if tool_name == "issue_refund" and "sub_id" in args:
                self.state.record_refund(
                    args["sub_id"], -float(args.get("amount", 0))
                )
            first = tool_result.violations[0] if tool_result.violations else None
            policy = first.policy if first else (tool_result.error_code or "unknown")
            detail = first.detail if first else (tool_result.message or "Rejected")
            logger.warning(
                "billing_blocked tool=%s session=%s policy=%s",
                tool_name, session_id, policy,
            )
            raise ToolBlocked(policy, detail)

        logger.info("allowed tool=%s session=%s", tool_name, session_id)
        return tool_result.model_dump(mode="json")
