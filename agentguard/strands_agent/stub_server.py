"""Contract v2 phase 2 billing server: MCP over Streamable HTTP (B2 stub).

Serves the four billing tools from any ``make_backend``-style factory, so the
Strands agent can be built and tested before Person A's servers land:

    python -m agentguard.strands_agent.stub_server --mode guarded            # :8002
    python -m agentguard.strands_agent.stub_server --mode naive              # :8001
    python -m agentguard.strands_agent.stub_server --backend tests.fakes:backend_factory

- Identity comes from the bearer token, never from tool arguments
  (``Authorization: Bearer demo-<customer_id>``).
- ``POST /admin/reset`` ``{"scenario_id": "S1"}`` reloads that scenario's seed.
- ``GET /admin/snapshot`` returns the backend state so runs can record
  initial and final state. Not in contract v2 yet: proposed addition.

Admin routes are plain HTTP, not MCP tools, so the agent cannot call them.
This is a local demo server: admin routes are unauthenticated.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import threading
from typing import Any, Callable

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..simulator.scenarios import SCENARIOS, Scenario, get_scenario

DEFAULT_PORTS = {"naive": 8001, "guarded": 8002}
TOKEN_PREFIX = "demo-"
SCOPE = "billing"

BackendFactory = Callable[[Scenario, str], Any]


def demo_token(customer_id: str) -> str:
    return f"{TOKEN_PREFIX}{customer_id}"


class DemoTokenVerifier:
    """Maps ``demo-<customer_id>`` tokens to that customer, for customers in the scenario seeds."""

    def __init__(self, customer_ids: set[str]) -> None:
        self.customer_ids = customer_ids

    async def verify_token(self, token: str) -> AccessToken | None:
        customer_id = token.removeprefix(TOKEN_PREFIX)
        if not token.startswith(TOKEN_PREFIX) or customer_id not in self.customer_ids:
            return None
        return AccessToken(token=token, client_id=customer_id, subject=customer_id, scopes=[SCOPE])


class ActiveScenario:
    """The scenario the server is currently serving, with a fresh backend per reset."""

    def __init__(self, factory: BackendFactory, mode: str, scenario_id: str = "S1") -> None:
        self.factory = factory
        self.mode = mode
        self.lock = threading.Lock()
        self.reset(scenario_id)

    def reset(self, scenario_id: str) -> Scenario:
        scenario = get_scenario(scenario_id)
        with self.lock:
            self.scenario = scenario
            self.backend = self.factory(scenario, self.mode)
        return scenario


def _identity_error(tool: str, args: dict[str, Any], actor: str | None, expected: str, mode: str) -> dict[str, Any]:
    reason = (
        "No valid bearer token." if actor is None
        else f"Signed in as {actor}, but the active scenario's customer is {expected}."
    )
    return {
        "receipt_version": 1, "mode": mode, "status": "ERROR", "tool": tool, "args": args,
        "actor_id": actor, "sub_id": None, "checks": [],
        "violated_policy": "invalid_arguments:TOKEN_SCENARIO_MISMATCH", "reason": reason,
        "safe_alternative": None, "approval_id": None, "executed": False,
        "money": {"refund_usd": 0.0, "discount_value_12m_usd": 0.0}, "result": None,
    }


def build_server(factory: BackendFactory, mode: str, host: str = "127.0.0.1", port: int | None = None) -> MCPServer:
    port = port or DEFAULT_PORTS[mode]
    customers = {cid for s in SCENARIOS for cid in s.seed}
    active = ActiveScenario(factory, mode)
    server = MCPServer(
        f"agentguard-billing-{mode}",
        instructions="StreamBox billing tools. Every call returns a decision receipt.",
        token_verifier=DemoTokenVerifier(customers),
        auth=AuthSettings(
            issuer_url=f"http://{host}:{port}",
            resource_server_url=f"http://{host}:{port}/mcp",
            required_scopes=[SCOPE],
        ),
    )

    def call(tool: str, **args: Any) -> dict[str, Any]:
        token = get_access_token()
        actor = token.subject if token else None
        with active.lock:
            expected = active.scenario.authenticated_customer_id
            if actor != expected:
                return _identity_error(tool, args, actor, expected, mode)
            return getattr(active.backend, tool)(**args)

    @server.tool()
    def get_subscription(customer_id: str) -> dict[str, Any]:
        """Look up a customer's subscription: plan, price, status, active discounts and payment history.
        Call this before changing anything."""
        return call("get_subscription", customer_id=customer_id)

    @server.tool()
    def apply_discount(customer_id: str, percent: float, reason: str) -> dict[str, Any]:
        """Apply a percentage discount (0-100) to a customer's subscription."""
        return call("apply_discount", customer_id=customer_id, percent=percent, reason=reason)

    @server.tool()
    def cancel_subscription(customer_id: str, reason: str) -> dict[str, Any]:
        """Cancel a customer's subscription."""
        return call("cancel_subscription", customer_id=customer_id, reason=reason)

    @server.tool()
    def issue_refund(customer_id: str, amount: float, reason: str) -> dict[str, Any]:
        """Refund money (USD) to a customer's original payment method."""
        return call("issue_refund", customer_id=customer_id, amount=amount, reason=reason)

    @server.custom_route("/admin/reset", methods=["POST"])
    async def reset(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            scenario = active.reset(body["scenario_id"])
        except (KeyError, ValueError) as exc:
            return JSONResponse({"error": f"bad reset request: {exc}"}, status_code=400)
        return JSONResponse({
            "scenario_id": scenario.id,
            "customer_id": scenario.authenticated_customer_id,
            "token": demo_token(scenario.authenticated_customer_id),
            "mode": mode,
        })

    @server.custom_route("/admin/snapshot", methods=["GET"])
    async def snapshot(request: Request) -> JSONResponse:
        with active.lock:
            return JSONResponse(active.backend.snapshot())

    return server


def load_factory(spec: str) -> BackendFactory:
    module_name, _, attr = spec.partition(":")
    return getattr(importlib.import_module(module_name), attr)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m agentguard.strands_agent.stub_server",
                                     description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=list(DEFAULT_PORTS), default="guarded")
    parser.add_argument("--port", type=int, help="default: 8001 naive, 8002 guarded")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--backend", default="agentguard.integration.backend:make_backend",
                        help="module:function returning a backend for (scenario, mode)")
    args = parser.parse_args(argv)

    sys.path.insert(0, os.getcwd())
    try:
        factory = load_factory(args.backend)
    except (ImportError, AttributeError) as exc:
        parser.error(f"cannot load backend {args.backend!r}: {exc}")
    port = args.port or DEFAULT_PORTS[args.mode]
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: admin routes are unauthenticated and demo tokens are guessable; "
              f"binding to {args.host} exposes them beyond this machine.", file=sys.stderr, flush=True)
    print(f"{args.mode} billing server on http://{args.host}:{port}/mcp (backend {args.backend})", flush=True)
    build_server(factory, args.mode, args.host, port).run("streamable-http", host=args.host, port=port)


if __name__ == "__main__":
    main()
