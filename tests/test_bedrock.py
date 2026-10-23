from types import SimpleNamespace

import pytest

from agentguard.simulator import BedrockLLM, GeminiLLM, AnthropicLLM, default_llm, get_scenario, run_scenario

from .fakes import backend_factory


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _msg(stop_reason, *blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))


def test_bedrock_runs_tool_loop_with_bedrock_model_id():
    tool_use = SimpleNamespace(type="tool_use", id="tu_1", name="get_subscription", input={"customer_id": "C-1001"})
    reply = SimpleNamespace(type="text", text="Here is your plan.")
    messages = FakeMessages([_msg("tool_use", tool_use), _msg("end_turn", reply)] + [_msg("end_turn", reply)] * 2)
    llm = BedrockLLM(client=SimpleNamespace(messages=messages))

    run = run_scenario(get_scenario("S1"), "naive", backend_factory, llm)

    assert run.status == "completed"
    assert run.tool_calls[0].executed
    first = messages.calls[0]
    assert first["model"] == "anthropic.claude-opus-5-5"
    assert all(t["strict"] for t in first["tools"])
    assert "betas" not in first and "fallbacks" not in first


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"AGENTGUARD_PROVIDER": "bedrock"}, BedrockLLM),
        ({"AGENTGUARD_PROVIDER": "gemini", "GEMINI_API_KEY": "x"}, GeminiLLM),
        ({"ANTHROPIC_API_KEY": "x"}, AnthropicLLM),
        ({"GEMINI_API_KEY": "x"}, GeminiLLM),
        ({}, BedrockLLM),
    ],
)
def test_default_llm_provider_selection(monkeypatch, env, expected):
    for key in ("AGENTGUARD_PROVIDER", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert isinstance(default_llm(), expected)


def test_default_llm_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("AGENTGUARD_PROVIDER", "openai")
    with pytest.raises(ValueError):
        default_llm()
