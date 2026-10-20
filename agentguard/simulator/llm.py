"""Thin LLM interface so the agent loop can run against Claude or a script."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

DEFAULT_MODEL = os.environ.get("AGENTGUARD_MODEL", "claude-opus-5-5")


@dataclass
class LLMResponse:
    stop_reason: str | None
    # Content blocks with ``.type`` plus ``.text`` (text) or ``.id``/``.name``/``.input`` (tool_use).
    # Appended back into the conversation unchanged.
    content: list[Any]


class LLMClient(Protocol):
    model: str

    def create(self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]) -> LLMResponse: ...


class AnthropicLLM:
    """Claude via the Anthropic SDK.

    Uses server-side refusal fallbacks so a safety-classifier refusal on the
    primary model is retried on a fallback model instead of ending the run.
    """

    def __init__(self, model: str = DEFAULT_MODEL, effort: str = "medium", client: Any = None) -> None:
        import anthropic

        self.model = model
        self.effort = effort
        self._client = client or anthropic.Anthropic()

    def create(self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]) -> LLMResponse:
        response = self._client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            tools=[{**tool, "strict": True} for tool in tools],
            messages=messages,
            output_config={"effort": self.effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        return LLMResponse(stop_reason=response.stop_reason, content=list(response.content))
