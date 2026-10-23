"""Backend whose tools run on the billing MCP servers (contract v2 phase 2).

``make_backend(scenario, mode)`` has the same shape as the in-process one, so the
web demo and the simulator can switch to the real servers with
``--backend agentguard.strands_agent.remote_backend:make_backend``. Each call
goes over MCP Streamable HTTP, signed in with the scenario customer's bearer
token; the receipt comes back from the server.

Server URLs: ``AGENTGUARD_NAIVE_URL`` / ``AGENTGUARD_GUARDED_URL``
(default http://localhost:8001/mcp and :8002/mcp).
"""

from __future__ import annotations

import itertools
import os
import threading
from typing import Any

from ..simulator.scenarios import Scenario
from .agent import DEFAULT_URLS, _admin, receipt_from_tool_result

_ids = itertools.count()


def server_url(mode: str) -> str:
    return os.environ.get(f"AGENTGUARD_{mode.upper()}_URL", DEFAULT_URLS[mode])


class RemoteBackend:
    """The four billing tools, executed on an MCP server; returns the server's receipts."""

    def __init__(self, scenario: Scenario, mode: str, url: str | None = None) -> None:
        from strands.tools.mcp import MCPClient

        self.scenario, self.mode = scenario, mode
        self.url = url or server_url(mode)
        reset = _admin(self.url, "/admin/reset", {"scenario_id": scenario.id})
        self._client = MCPClient(url=self.url, headers={"Authorization": f"Bearer {reset['token']}"}).start()
        self._lock = threading.Lock()

    def _call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        with self._lock:
            result = self._client.call_tool_sync(f"remote-{next(_ids)}", tool, arguments)
        receipt = receipt_from_tool_result(dict(result))
        if receipt is None:
            text = " ".join(b.get("text", "") for b in result.get("content", []) if isinstance(b, dict))
            return {"status": "ERROR", "tool": tool, "args": arguments, "checks": [], "executed": False,
                    "violated_policy": "invalid_arguments:NO_RECEIPT", "safe_alternative": None,
                    "approval_id": None, "result": None, "reason": text.strip() or "The server returned no receipt."}
        return receipt

    def get_subscription(self, customer_id: str) -> dict[str, Any]:
        return self._call("get_subscription", customer_id=customer_id)

    def apply_discount(self, customer_id: str, percent: float, reason: str) -> dict[str, Any]:
        return self._call("apply_discount", customer_id=customer_id, percent=percent, reason=reason)

    def cancel_subscription(self, customer_id: str, reason: str) -> dict[str, Any]:
        return self._call("cancel_subscription", customer_id=customer_id, reason=reason)

    def issue_refund(self, customer_id: str, amount: float, reason: str) -> dict[str, Any]:
        return self._call("issue_refund", customer_id=customer_id, amount=amount, reason=reason)

    def snapshot(self) -> dict[str, Any]:
        return _admin(self.url, "/admin/snapshot")

    def close(self) -> None:
        self._client.stop(None, None, None)


def make_backend(scenario: Scenario, mode: str) -> RemoteBackend:
    return RemoteBackend(scenario, mode)
