"""Thin LLM interface so the agent loop can run against Claude or a script."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = os.environ.get("AGENTGUARD_MODEL", "claude-opus-5-5")
DEFAULT_GEMINI_MODEL = os.environ.get("AGENTGUARD_GEMINI_MODEL", "gemini-3.8-flash")
DEFAULT_BEDROCK_MODEL = os.environ.get("AGENTGUARD_BEDROCK_MODEL", "anthropic.claude-opus-5-5")
DEFAULT_GROQ_MODEL = os.environ.get("AGENTGUARD_GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


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


class BedrockLLM:
    """Claude on Amazon Bedrock via the Anthropic SDK's Bedrock (Mantle) client.

    Credentials come from the standard AWS chain: AWS_ACCESS_KEY_ID /
    AWS_SECRET_ACCESS_KEY, AWS_PROFILE, or AWS_BEARER_TOKEN_BEDROCK. The model
    needs to be enabled in the Bedrock console for the account and region.
    Server-side refusal fallbacks are not used here; a refusal ends the run
    with status "refusal".
    """

    def __init__(self, model: str = DEFAULT_BEDROCK_MODEL, region: str | None = None, client: Any = None) -> None:
        from anthropic import AnthropicBedrockMantle

        self.model = model
        self.region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
        self._client = client or AnthropicBedrockMantle(aws_region=self.region)

    def create(self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]) -> LLMResponse:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            tools=[{**tool, "strict": True} for tool in tools],
            messages=messages,
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


@dataclass
class ChatBlock:
    """Content block in the shape the agent loop reads (text or tool_use)."""

    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


class OpenAICompatLLM:
    """Any OpenAI-compatible chat endpoint with tool calling (Groq by default).

    The agent keeps its history in Anthropic message format; this class
    translates it to chat-completions messages on every call.
    """

    def __init__(self, model: str = DEFAULT_GROQ_MODEL, base_url: str = GROQ_BASE_URL,
                 api_key: str | None = None, client: Any = None) -> None:
        self.model = model
        if client is None:
            from openai import OpenAI

            client = OpenAI(base_url=base_url, api_key=api_key or os.environ.get("GROQ_API_KEY"),
                            max_retries=6, timeout=120)
        self._client = client

    def create(self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]) -> LLMResponse:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, *self._to_chat(messages)],
            tools=[{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                     "parameters": t["input_schema"]}} for t in tools],
            tool_choice="auto",
        )
        choice = response.choices[0]
        message = choice.message
        blocks: list[ChatBlock] = []
        if message.content:
            blocks.append(ChatBlock("text", text=message.content))
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except ValueError:
                arguments = {}
            blocks.append(ChatBlock("tool_use", id=call.id, name=call.function.name, input=arguments))
        if any(b.type == "tool_use" for b in blocks):
            stop_reason = "tool_use"
        elif choice.finish_reason == "content_filter":
            stop_reason = "refusal"
        else:
            stop_reason = "end_turn"
        return LLMResponse(stop_reason=stop_reason, content=blocks)

    @staticmethod
    def _to_chat(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for message in messages:
            content = message["content"]
            if message["role"] == "assistant":
                text = "".join(_field(b, "text") or "" for b in content if _field(b, "type") == "text")
                calls = [{"id": _field(b, "id"), "type": "function",
                          "function": {"name": _field(b, "name"), "arguments": json.dumps(_field(b, "input") or {})}}
                         for b in content if _field(b, "type") == "tool_use"]
                out.append({"role": "assistant", "content": text or None, **({"tool_calls": calls} if calls else {})})
            elif isinstance(content, str):
                out.append({"role": "user", "content": content})
            else:
                for block in content:
                    if _field(block, "type") == "tool_result":
                        out.append({"role": "tool", "tool_call_id": _field(block, "tool_use_id"),
                                    "content": str(_field(block, "content"))})
        return out


def default_llm() -> LLMClient:
    """Pick the provider from AGENTGUARD_PROVIDER (bedrock | anthropic | gemini | groq).

    Without it: Anthropic if ANTHROPIC_API_KEY is set, else Gemini if a Gemini
    key is set, else Groq if GROQ_API_KEY is set, else Bedrock (AWS credentials).
    """
    provider = os.environ.get("AGENTGUARD_PROVIDER", "").lower()
    if not provider:
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            provider = "gemini"
        elif os.environ.get("GROQ_API_KEY"):
            provider = "groq"
        else:
            provider = "bedrock"
    if provider == "gemini":
        return GeminiLLM()
    if provider == "bedrock":
        return BedrockLLM()
    if provider == "anthropic":
        return AnthropicLLM()
    if provider == "groq":
        return OpenAICompatLLM()
    raise ValueError(f"Unknown AGENTGUARD_PROVIDER {provider!r}; use bedrock, anthropic, gemini or groq")
