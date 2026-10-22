"""MCP server: exposes billing tools with policy enforcement.

Run over stdio:
    python -m agentguard.mcp.server
"""
from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from .handler import BillingHandler, ToolBlocked

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("AgentGuard Billing", json_response=True)
handler = BillingHandler()


def _call(tool: str, arguments: dict, session_id: str) -> dict:
    try:
        return handler.handle(tool, arguments, session_id)
    except ToolBlocked as exc:
        from mcp.server.fastmcp.exceptions import ToolError
        raise ToolError(str(exc)) from exc


@mcp.tool()
def issue_refund(
    session_id: str,
    actor_id: str,
    charge_id: str,
    amount: float,
    reason: str,
) -> dict:
    """Issue a refund. Blocked if policy violation (cap, cumulative, window, reason)."""
    return _call(
        "issue_refund",
        {
            "charge_id": charge_id,
            "amount": amount,
            "reason": reason,
            "actor_id": actor_id,
        },
        session_id,
    )


@mcp.tool()
def get_subscription(session_id: str, customer_id: str) -> dict:
    """Look up a customer's subscription (read-only; never blocked)."""
    return _call("get_subscription", {"customer_id": customer_id}, session_id)


@mcp.tool()
def apply_discount(
    session_id: str, actor_id: str, subscription_id: str, percent: float
) -> dict:
    """Apply a discount. Blocked if percent exceeds policy or already used."""
    return _call(
        "apply_discount",
        {
            "subscription_id": subscription_id,
            "percent": percent,
            "actor_id": actor_id,
        },
        session_id,
    )


@mcp.tool()
def cancel_subscription(session_id: str, actor_id: str, subscription_id: str) -> dict:
    """Cancel a subscription. Blocked if not owned by the acting customer."""
    return _call(
        "cancel_subscription",
        {"subscription_id": subscription_id, "actor_id": actor_id},
        session_id,
    )


def main() -> None:
    logger.info("starting AgentGuard MCP server (stdio)")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
