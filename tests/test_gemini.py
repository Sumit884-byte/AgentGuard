from google.genai import types

from agentguard.simulator import GeminiLLM, get_scenario, run_scenario

from .fakes import backend_factory


def _response(*parts, finish="STOP"):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)), finish_reason=finish)]
    )


def _call(name, **args):
    return types.Part(function_call=types.FunctionCall(id=f"id_{name}", name=name, args=args), thought_signature=b"sig")


class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def generate_content(self, model, contents, config):
        self.requests.append(contents)
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)


def test_gemini_tool_loop_translates_and_keeps_thought_signatures():
    client = FakeClient(
        [
            _response(_call("apply_discount", customer_id="C-1001", percent=80, reason="retention")),
            _response(types.Part(text="Sorry, I can't do 80%.")),
            _response(types.Part(text="ok")),
            _response(types.Part(text="ok")),
        ]
    )
    llm = GeminiLLM(model="gemini-test", client=client)
    run = run_scenario(get_scenario("S1"), "guarded", backend_factory, llm)

    assert run.status == "completed"
    assert run.blocked_calls[0].tool_name == "apply_discount"

    second_request = client.models.requests[1]
    model_turn, tool_turn = second_request[1], second_request[2]
    assert model_turn.role == "model"
    assert model_turn.parts[0].thought_signature == b"sig"
    response = tool_turn.parts[0].function_response
    assert response.name == "apply_discount"
    assert response.id == "id_apply_discount"
    assert response.response["error"].startswith("Blocked by billing policy: Discounts are capped at 20%.")


def test_gemini_safety_block_maps_to_refusal():
    client = FakeClient([types.GenerateContentResponse(candidates=[types.Candidate(finish_reason="SAFETY")])])
    run = run_scenario(get_scenario("S1"), "naive", backend_factory, GeminiLLM(model="g", client=client))
    assert run.status == "refusal"


def test_gemini_retries_transient_errors(monkeypatch):
    import httpx
    from google.genai import errors

    monkeypatch.setattr("agentguard.simulator.llm.time.sleep", lambda s: None)
    outcomes = [
        errors.ServerError(503, {"error": {"message": "high demand"}}),
        httpx.RemoteProtocolError("Server disconnected"),
        _response(types.Part(text="hello")),
    ]

    class Flaky:
        def generate_content(self, **kwargs):
            item = outcomes.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    class Client:
        models = Flaky()

    result = GeminiLLM(model="g", client=Client()).create("s", [], [{"role": "user", "content": "hi"}])
    assert result.content[0].text == "hello"


def test_gemini_does_not_retry_bad_request(monkeypatch):
    import pytest
    from google.genai import errors

    calls = []

    class Bad:
        def generate_content(self, **kwargs):
            calls.append(1)
            raise errors.ClientError(400, {"error": {"message": "bad schema"}})

    class Client:
        models = Bad()

    with pytest.raises(errors.ClientError):
        GeminiLLM(model="g", client=Client()).create("s", [], [{"role": "user", "content": "hi"}])
    assert len(calls) == 1
