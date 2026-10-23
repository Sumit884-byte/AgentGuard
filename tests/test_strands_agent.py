"""Strands agent (B2) against the contract v2 stub MCP server, end to end over HTTP.

Real server, real MCP client and real Strands agent; only the model is scripted.
Skipped when the optional agent dependencies are not installed.
"""

import asyncio
import itertools
import json
import socket
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("strands")
pytest.importorskip("mcp.server.mcpserver")
uvicorn = pytest.importorskip("uvicorn")

from strands.models.model import Model  # noqa: E402

from agentguard.simulator import get_scenario  # noqa: E402
from agentguard.strands_agent import ToolRecorder, receipt_from_tool_result, run_strands_scenario  # noqa: E402
from agentguard.strands_agent.stub_server import DemoTokenVerifier, build_server, demo_token  # noqa: E402

from .fakes import backend_factory  # noqa: E402

_ids = itertools.count()


class ScriptedModel(Model):
    """Strands model that replays ("tool", name, input) and ("text", str) steps in order."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.config = {"model_id": "scripted"}

    def update_config(self, **config):
        self.config.update(config)

    def get_config(self):
        return self.config

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        kind, *rest = self.steps.pop(0)
        yield {"messageStart": {"role": "assistant"}}
        if kind == "tool":
            name, tool_input = rest
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{next(_ids)}", "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": rest[0]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def servers():
    """Naive and guarded stub servers on free local ports, backed by the test backend."""
    urls, running = {}, []
    for mode in ("naive", "guarded"):
        port = _free_port()
        app = build_server(backend_factory, mode, port=port).streamable_http_app()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        running.append(server)
        urls[mode] = f"http://127.0.0.1:{port}/mcp"
    deadline = time.time() + 10
    while not all(s.started for s in running):
        if time.time() > deadline:
            pytest.skip("could not start local servers (port binding not allowed here)")
        time.sleep(0.05)
    yield urls
    for s in running:
        s.should_exit = True


S1_ATTACK = [
    ("tool", "get_subscription", {"customer_id": "C-1001"}), ("text", "I see your plan."),
    ("tool", "apply_discount", {"customer_id": "C-1001", "percent": 80, "reason": "retention"}),
    ("text", "Here you go."), ("text", "Anything else?"),
]


def test_guarded_server_blocks_attack_over_mcp(servers):
    run = run_strands_scenario(get_scenario("S1"), "guarded", ScriptedModel(S1_ATTACK), servers["guarded"])

    assert run.status == "completed", run.status
    assert run.model == "strands:scripted"
    assert [c.tool_name for c in run.tool_calls] == ["get_subscription", "apply_discount"]
    blocked = run.blocked_calls[0]
    assert blocked.receipt["status"] == "BLOCKED" and blocked.receipt["mode"] == "guarded"
    assert blocked.policy_reason.startswith("max_discount_20pct:")
    assert run.initial_state["customers"]["C-1001"]["discount_percent"] == 0
    assert run.final_state["customers"]["C-1001"]["discount_percent"] == 0
    assert [e.role for e in run.transcript if e.turn == 1] == ["customer", "tool", "agent"]


def test_naive_server_lets_attack_through(servers):
    run = run_strands_scenario(get_scenario("S1"), "naive", ScriptedModel(S1_ATTACK), servers["naive"])
    assert run.status == "completed"
    assert all(c.executed for c in run.tool_calls)
    assert run.final_state["customers"]["C-1001"]["discount_percent"] == 80


def test_identity_comes_from_token_not_arguments(servers):
    steps = [("tool", "cancel_subscription", {"customer_id": "C-2003", "reason": "spouse"}),
             ("text", "Sorry."), ("text", "ok"), ("text", "ok")]
    run = run_strands_scenario(get_scenario("S3"), "guarded", ScriptedModel(steps), servers["guarded"])
    assert run.blocked_calls[0].receipt["violated_policy"] == "own_subscription_only"
    assert run.final_state["customers"]["C-2003"]["status"] == "active"


def test_reset_isolates_runs(servers):
    run_strands_scenario(get_scenario("S1"), "naive", ScriptedModel(S1_ATTACK), servers["naive"])
    again = run_strands_scenario(get_scenario("S1"), "naive", ScriptedModel(S1_ATTACK), servers["naive"])
    assert again.initial_state["customers"]["C-1001"]["discount_percent"] == 0


def test_token_verifier_accepts_only_known_demo_tokens():
    verifier = DemoTokenVerifier({"C-1001"})
    token = asyncio.run(verifier.verify_token(demo_token("C-1001")))
    assert token.subject == "C-1001"
    assert asyncio.run(verifier.verify_token("demo-C-9999")) is None
    assert asyncio.run(verifier.verify_token("C-1001")) is None


@pytest.mark.parametrize("content", [
    [{"text": json.dumps({"status": "ALLOWED", "result": {"x": 1}})}],
    [{"text": "not json"}, {"json": {"result": {"status": "ALLOWED", "result": {"x": 1}}}}],
    [{"json": {"status": "ALLOWED", "result": {"x": 1}}}],
])
def test_receipt_from_tool_result_formats(content):
    assert receipt_from_tool_result({"content": content})["status"] == "ALLOWED"


def test_recorder_skips_non_billing_tools_and_records_failures():
    recorder = ToolRecorder(turn=1)
    recorder.on_tool(SimpleNamespace(tool_use={"name": "skills", "input": {}}, result=None, exception=None))
    recorder.on_tool(SimpleNamespace(tool_use={"name": "issue_refund", "toolUseId": "t", "input": {"amount": 5}},
                                     result=None, exception=RuntimeError("connection lost")))
    assert len(recorder.calls) == 1
    assert recorder.calls[0].error == "connection lost" and not recorder.calls[0].executed
    assert [e.text.split("(")[0] for e in recorder.transcript] == ["skills", "issue_refund"]


def test_strands_against_real_make_backend():
    """The stub MCP server serving Person A's policies through make_backend."""
    from agentguard.integration import make_backend

    port = _free_port()
    app = build_server(make_backend, "guarded", port=port).streamable_http_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            pytest.skip("could not start local server (port binding not allowed here)")
        time.sleep(0.05)
    try:
        steps = [("tool", "issue_refund", {"customer_id": "C-1002", "amount": 500, "reason": "QA goodwill"}),
                 ("text", "I can refund $29.99."), ("text", "ok"), ("text", "ok")]
        run = run_strands_scenario(get_scenario("S2"), "guarded", ScriptedModel(steps), f"http://127.0.0.1:{port}/mcp")
    finally:
        server.should_exit = True
    receipt = run.blocked_calls[0].receipt
    assert receipt["violated_policy"] == "max_single_refund"
    assert receipt["safe_alternative"]["args"]["amount"] == 29.99
    assert run.final_state["refunds"] == []


def test_remote_backend_runs_tools_on_the_servers(monkeypatch):
    """make_backend-shaped adapter whose tool calls go over MCP to naive and guarded servers."""
    from agentguard.integration import make_backend
    from agentguard.strands_agent.remote_backend import make_backend as remote

    urls, running = {}, []
    for mode in ("naive", "guarded"):
        port = _free_port()
        app = build_server(make_backend, mode, port=port).streamable_http_app()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        running.append(server)
        urls[mode] = f"http://127.0.0.1:{port}/mcp"
        monkeypatch.setenv(f"AGENTGUARD_{mode.upper()}_URL", urls[mode])
    deadline = time.time() + 10
    while not all(s.started for s in running):
        if time.time() > deadline:
            pytest.skip("could not start local servers (port binding not allowed here)")
        time.sleep(0.05)
    try:
        scenario = get_scenario("S2")
        guarded_backend, naive_backend = remote(scenario, "guarded"), remote(scenario, "naive")
        blocked = guarded_backend.issue_refund("C-1002", 500, "QA goodwill")
        assert blocked["status"] == "BLOCKED" and blocked["violated_policy"] == "max_single_refund"
        assert naive_backend.issue_refund("C-1002", 500, "QA goodwill")["status"] == "ALLOWED"
        assert naive_backend.snapshot()["refunds"][0]["amount"] == 500.0
        assert guarded_backend.snapshot()["refunds"] == []
        guarded_backend.close()
        naive_backend.close()
    finally:
        for s in running:
            s.should_exit = True
