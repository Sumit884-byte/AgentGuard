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


def _mantle_client(handler):
    """The real Bedrock (Mantle) client with only the network replaced."""
    import httpx2
    from anthropic import AnthropicBedrockMantle, DefaultHttpxClient

    return AnthropicBedrockMantle(
        aws_region="us-west-2", aws_access_key="test-key-id", aws_secret_key="test-secret",
        http_client=DefaultHttpxClient(transport=httpx2.MockTransport(handler)), max_retries=0,
    )


def _message(body, *blocks, stop_reason="end_turn"):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"], "content": list(blocks),
            "stop_reason": stop_reason, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}


def test_bedrock_request_is_signed_and_sent_to_regional_endpoint():
    import json

    import httpx2

    seen = {}

    def handler(request):
        seen["url"], seen["headers"], seen["body"] = str(request.url), request.headers, json.loads(request.content)
        return httpx2.Response(200, json=_message(seen["body"], {"type": "text", "text": "hi"}))

    from agentguard.simulator import DEFAULT_BEDROCK_MODEL, TOOL_SPECS

    result = BedrockLLM(client=_mantle_client(handler)).create("system", TOOL_SPECS, [{"role": "user", "content": "hi"}])

    assert result.stop_reason == "end_turn" and result.content[0].text == "hi"
    assert seen["url"] == "https://bedrock-mantle.us-west-2.api.aws/anthropic/v1/messages"
    assert seen["headers"]["authorization"].startswith("AWS4-HMAC-SHA256 Credential=test-key-id/")
    assert seen["body"]["model"] == DEFAULT_BEDROCK_MODEL
    assert seen["body"]["system"] == "system"
    assert [t["name"] for t in seen["body"]["tools"]] == [t["name"] for t in TOOL_SPECS]
    assert all(t["strict"] for t in seen["body"]["tools"])


def test_bedrock_scenario_over_http_mock():
    import json

    import httpx2

    responses = iter([
        ("tool_use", {"type": "tool_use", "id": "tu_1", "name": "get_subscription", "input": {"customer_id": "C-1001"}}),
        *[("end_turn", {"type": "text", "text": "Done."})] * 3,
    ])

    def handler(request):
        stop, block = next(responses)
        return httpx2.Response(200, json=_message(json.loads(request.content), block, stop_reason=stop))

    run = run_scenario(get_scenario("S1"), "guarded", backend_factory, BedrockLLM(client=_mantle_client(handler)))
    assert run.status == "completed"
    assert run.tool_calls[0].executed and run.tool_calls[0].receipt["status"] == "ALLOWED"


def test_strands_make_model_builds_bedrock_and_gemini(monkeypatch):
    pytest.importorskip("strands")
    from agentguard.strands_agent import make_model

    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key-id")  # no credential lookup over the network
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("AGENTGUARD_BEDROCK_MODEL", "my-model")
    bedrock = make_model("bedrock")
    assert bedrock.get_config()["model_id"] == "my-model"
    assert bedrock.client.meta.region_name == "eu-west-1"

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    assert make_model("gemini").get_config()["model_id"]
    with pytest.raises(ValueError):
        make_model("openai")
