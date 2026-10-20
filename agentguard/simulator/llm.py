"""Thin LLM interface so the agent loop can run against Claude or a script."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = os.environ.get("AGENTGUARD_MODEL", "claude-opus-5-5")
DEFAULT_GEMINI_MODEL = os.environ.get("AGENTGUARD_GEMINI_MODEL", "gemini-3.8-flash")


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


@dataclass
class GeminiBlock:
    """Content block in the same shape the agent loop reads from Claude."""

    type: str  # "text" or "tool_use"
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    # The original Gemini part. Sent back unchanged so thought signatures survive.
    part: Any = None


def _field(block: Any, key: str, default: Any = None) -> Any:
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


class GeminiLLM:
    """Gemini via the google-genai SDK.

    The agent keeps its conversation in Anthropic message format; this class
    translates it to Gemini ``contents`` on every call. Reads GEMINI_API_KEY
    (or GOOGLE_API_KEY) from the environment.
    """

    RETRY_DELAYS = (2, 5, 10, 20, 40)  # seconds; Gemini 503s under load are common and short-lived

    def __init__(self, model: str = DEFAULT_GEMINI_MODEL, client: Any = None, timeout_s: float = 120) -> None:
        from google import genai

        self.model = model
        self._client = client or genai.Client(http_options={"timeout": int(timeout_s * 1000)})

    def _generate(self, contents: list[Any], config: Any) -> Any:
        import httpx
        from google.genai import errors

        for delay in (*self.RETRY_DELAYS, None):
            try:
                return self._client.models.generate_content(model=self.model, contents=contents, config=config)
            except (errors.ServerError, errors.ClientError, httpx.TransportError) as exc:
                retryable = not isinstance(exc, errors.ClientError) or exc.code == 429
                if not retryable or delay is None:
                    raise
                time.sleep(delay)

    def create(self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]) -> LLMResponse:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t["name"],
                            description=t["description"],
                            parameters_json_schema=t["input_schema"],
                        )
                        for t in tools
                    ]
                )
            ],
            # The agent loop executes tools itself; never let the SDK call anything.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._generate(self._to_contents(messages), config)

        candidate = (response.candidates or [None])[0]
        parts = list(candidate.content.parts or []) if candidate and candidate.content else []
        blocks: list[GeminiBlock] = []
        for i, part in enumerate(parts):
            if part.function_call:
                call = part.function_call
                blocks.append(
                    GeminiBlock(
                        "tool_use",
                        id=call.id or f"gemini_call_{len(messages)}_{i}",
                        name=call.name,
                        input=dict(call.args or {}),
                        part=part,
                    )
                )
            elif part.text and not part.thought:
                blocks.append(GeminiBlock("text", text=part.text, part=part))
            else:
                blocks.append(GeminiBlock("other", part=part))  # thoughts etc., replayed as-is

        if any(b.type == "tool_use" for b in blocks):
            stop_reason = "tool_use"
        elif candidate is None or str(candidate.finish_reason).endswith(("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST")):
            stop_reason = "refusal"
        else:
            stop_reason = "end_turn"
        return LLMResponse(stop_reason=stop_reason, content=blocks)

    @staticmethod
    def _to_contents(messages: list[dict[str, Any]]) -> list[Any]:
        from google.genai import types

        names_by_id: dict[str, str] = {}
        contents = []
        for message in messages:
            content = message["content"]
            if message["role"] == "assistant":
                parts = []
                for block in content:
                    if _field(block, "type") == "tool_use":
                        names_by_id[_field(block, "id")] = _field(block, "name")
                    part = _field(block, "part")
                    if part is not None:
                        parts.append(part)
                    elif _field(block, "type") == "text":
                        parts.append(types.Part(text=_field(block, "text")))
                    elif _field(block, "type") == "tool_use":
                        parts.append(
                            types.Part(
                                function_call=types.FunctionCall(
                                    id=_field(block, "id"), name=_field(block, "name"), args=_field(block, "input")
                                )
                            )
                        )
                if parts:
                    contents.append(types.Content(role="model", parts=parts))
            elif isinstance(content, str):
                contents.append(types.Content(role="user", parts=[types.Part(text=content)]))
            else:
                parts = []
                for block in content:
                    if _field(block, "type") != "tool_result":
                        continue
                    raw = _field(block, "content")
                    try:
                        payload = json.loads(raw)
                    except (TypeError, ValueError):
                        payload = raw
                    key = "error" if _field(block, "is_error") else "output"
                    parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=_field(block, "tool_use_id"),
                                name=names_by_id.get(_field(block, "tool_use_id"), ""),
                                response={key: payload},
                            )
                        )
                    )
                contents.append(types.Content(role="user", parts=parts))
        return contents


def default_llm() -> LLMClient:
    """Pick the provider from AGENTGUARD_PROVIDER, else from whichever key is set."""
    provider = os.environ.get("AGENTGUARD_PROVIDER", "").lower()
    if not provider:
        has_gemini = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        provider = "gemini" if has_gemini and not os.environ.get("ANTHROPIC_API_KEY") else "anthropic"
    return GeminiLLM() if provider == "gemini" else AnthropicLLM()
