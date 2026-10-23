import json
from types import SimpleNamespace

from agentguard.simulator import OpenAICompatLLM, get_scenario, run_scenario

from .fakes import backend_factory


def _completion(content=None, tool_calls=None, finish="stop"):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)])


def _call(call_id, name, **args):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeCompletions:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def test_tool_loop_translates_history_both_ways():
    completions = FakeCompletions([
        _completion(tool_calls=[_call("c1", "apply_discount", customer_id="C-1001", percent=80, reason="x")],
                    finish="tool_calls"),
        _completion("I can offer 20% instead."), _completion("ok"), _completion("ok"),
    ])
    llm = OpenAICompatLLM(model="test-model", client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    run = run_scenario(get_scenario("S1"), "guarded", backend_factory, llm)

    assert run.status == "completed"
    assert run.blocked_calls[0].receipt["violated_policy"] == "max_discount_20pct"
    second = completions.requests[1]
    assert second["model"] == "test-model" and second["messages"][0]["role"] == "system"
    assistant, tool_msg = second["messages"][2], second["messages"][3]
    assert assistant["tool_calls"][0]["function"]["name"] == "apply_discount"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"])["percent"] == 80
    assert tool_msg == {"role": "tool", "tool_call_id": "c1", "content": tool_msg["content"]}
    assert tool_msg["content"].startswith("Blocked by billing policy")
    assert second["tools"][0]["type"] == "function"


def test_content_filter_is_a_refusal():
    completions = FakeCompletions([_completion(None, None, finish="content_filter")])
    llm = OpenAICompatLLM(model="m", client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    assert run_scenario(get_scenario("S1"), "naive", backend_factory, llm).status == "refusal"
