"""Strands agent as the MCP client of the billing servers (B2).

Same system prompt as the in-process agent. The agent reaches the tools only
through MCP over Streamable HTTP, signed in with the scenario customer's bearer
token, so naive vs guarded is just a different server URL.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..simulator.agent import SYSTEM_PROMPT
from ..simulator.llm import DEFAULT_BEDROCK_MODEL, DEFAULT_GEMINI_MODEL
from ..simulator.records import ScenarioRun, ToolCallRecord, TranscriptEntry
from ..simulator.scenarios import Scenario
from ..simulator.tools import TOOL_NAMES, apply_receipt

DEFAULT_URLS = {"naive": "http://localhost:8001/mcp", "guarded": "http://localhost:8002/mcp"}
REFUSAL_STOP_REASONS = {"guardrail_intervened", "content_filtered"}


def make_model(provider: str = "bedrock") -> Any:
    """Bedrock is the target (AWS Builder track); Gemini lets the same loop run without AWS."""
    if provider == "bedrock":
        from strands.models.bedrock import BedrockModel

        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
        return BedrockModel(model_id=os.environ.get("AGENTGUARD_BEDROCK_MODEL", DEFAULT_BEDROCK_MODEL),
                            region_name=region)
    if provider == "gemini":
        from strands.models.gemini import GeminiModel

        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        return GeminiModel(client_args={"api_key": key},
                           model_id=os.environ.get("AGENTGUARD_GEMINI_MODEL", DEFAULT_GEMINI_MODEL))
    raise ValueError(f"unknown provider {provider!r}; use bedrock or gemini")


def model_label(model: Any) -> str:
    config = model.get_config() if hasattr(model, "get_config") else {}
    return f"strands:{config.get('model_id', type(model).__name__)}"


def receipt_from_tool_result(result: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the decision receipt out of a Strands tool result for an MCP call.

    MCP tools return the receipt as structured content (a ``json`` block) and as
    JSON text; structured content may be wrapped as ``{"result": receipt}``.
    """
    for block in reversed(result.get("content") or []):
        data = block.get("json")
        if data is None and "text" in block:
            try:
                data = json.loads(block["text"])
            except (TypeError, ValueError):
                continue
        if isinstance(data, dict) and "status" not in data and isinstance(data.get("result"), dict):
            data = data["result"]
        if isinstance(data, dict) and "status" in data:
            return data
    return None


@dataclass
class ToolRecorder:
    """Strands AfterToolCallEvent hook: one ToolCallRecord per billing tool call."""

    turn: int = 0
    calls: list[ToolCallRecord] = field(default_factory=list)
    transcript: list[TranscriptEntry] = field(default_factory=list)

    def on_tool(self, event: Any) -> None:
        tool_use = event.tool_use
        name = tool_use.get("name", "")
        if name not in TOOL_NAMES:  # e.g. the skills plugin's own tool
            self.transcript.append(TranscriptEntry(self.turn, "tool", f"{name}({tool_use.get('input')})"))
            return
        record = ToolCallRecord(
            turn=self.turn, tool_use_id=tool_use.get("toolUseId", ""), tool_name=name,
            arguments=dict(tool_use.get("input") or {}), allowed=True, executed=False,
        )
        self.calls.append(record)
        receipt = receipt_from_tool_result(event.result or {}) if event.exception is None else None
        if receipt is not None:
            content, _ = apply_receipt(record, receipt)
        else:
            record.error = str(event.exception) if event.exception else "no receipt in tool result"
            content = f"Error: {record.error}"
        self.transcript.append(TranscriptEntry(self.turn, "tool", f"{name}({record.arguments}) -> {content}"))


def _admin(server_url: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base = server_url.rsplit("/mcp", 1)[0]
    with httpx.Client(timeout=30) as http:
        response = http.post(base + path, json=payload) if payload is not None else http.get(base + path)
        response.raise_for_status()
        return response.json()


def run_strands_scenario(
    scenario: Scenario,
    mode: str,
    model: Any,
    server_url: str | None = None,
    skills: list[str] | None = None,
) -> ScenarioRun:
    """Play one scenario against a billing MCP server and return a ScenarioRun."""
    from strands import Agent
    from strands.hooks import AfterToolCallEvent
    from strands.tools.mcp import MCPClient

    server_url = server_url or DEFAULT_URLS[mode]
    reset = _admin(server_url, "/admin/reset", {"scenario_id": scenario.id})
    recorder = ToolRecorder()
    run = ScenarioRun(
        scenario_id=scenario.id, attack_type=scenario.attack_type, mode=mode, model=model_label(model),
        authenticated_customer_id=scenario.authenticated_customer_id,
        targeted_policies=list(scenario.targeted_policies),
        initial_state=_admin(server_url, "/admin/snapshot"), final_state={},
    )

    plugins = []
    if skills:
        from strands.vended_plugins.skills import AgentSkills

        plugins.append(AgentSkills(skills=skills))

    client = MCPClient(url=server_url, headers={"Authorization": f"Bearer {reset['token']}"})
    try:
        with client:
            agent = Agent(
                model=model,
                tools=client.list_tools_sync(),
                system_prompt=SYSTEM_PROMPT.format(customer_id=scenario.authenticated_customer_id),
                plugins=plugins or None,
                callback_handler=None,
            )
            agent.hooks.add_callback(AfterToolCallEvent, recorder.on_tool)
            for turn, message in enumerate(scenario.customer_messages, start=1):
                recorder.turn = turn
                recorder.transcript.append(TranscriptEntry(turn, "customer", message))
                result = agent(message)
                text = str(result).strip()
                if text:
                    recorder.transcript.append(TranscriptEntry(turn, "agent", text))
                if result.stop_reason in REFUSAL_STOP_REASONS:
                    run.status = "refusal"
                    break
    except Exception as exc:  # keep partial artifacts, as the in-process runner does
        run.status = f"error: {type(exc).__name__}: {exc}"

    run.transcript = recorder.transcript
    run.tool_calls = recorder.calls
    run.final_state = _admin(server_url, "/admin/snapshot")
    return run
