"""Adversarial customer simulator and billing support agent (naive + guarded)."""

from .agent import SYSTEM_PROMPT, SupportAgent
from .contracts import BillingBackend, Receipt
from .llm import DEFAULT_GEMINI_MODEL, DEFAULT_MODEL, AnthropicLLM, GeminiLLM, LLMClient, LLMResponse, default_llm
from .records import ScenarioRun, ToolCallRecord, TranscriptEntry
from .runner import BackendFactory, run_scenario, run_suite
from .scenarios import SCENARIOS, SCENARIOS_BY_ID, Scenario, get_scenario
from .tools import TOOL_SPECS, ToolExecutor

__all__ = [
    "DEFAULT_GEMINI_MODEL",
    "DEFAULT_MODEL",
    "SCENARIOS",
    "SCENARIOS_BY_ID",
    "SYSTEM_PROMPT",
    "TOOL_SPECS",
    "AnthropicLLM",
    "BackendFactory",
    "BillingBackend",
    "GeminiLLM",
    "LLMClient",
    "LLMResponse",
    "Receipt",
    "Scenario",
    "ScenarioRun",
    "SupportAgent",
    "ToolCallRecord",
    "ToolExecutor",
    "TranscriptEntry",
    "default_llm",
    "get_scenario",
    "run_scenario",
    "run_suite",
]
