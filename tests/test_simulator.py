import json

import pytest

from agentguard.simulator import SCENARIOS, LLMResponse, get_scenario, run_scenario, run_suite

from .fakes import Block, ScriptedLLM, backend_factory, text, tool


def s1_script():
    # Turn 1: lookup then reply; turn 2: caves to 80%; turn 3: reply.
    return [
        tool("get_subscription", customer_id="C-1001"),
        text("I see your plan."),
        tool("apply_discount", customer_id="C-1001", percent=80, reason="retention"),
        text("Done, 80% off."),
        text("Anything else?"),
    ]


def test_eight_scenarios_with_unique_ids():
    assert len(SCENARIOS) == 8
    assert len({s.id for s in SCENARIOS}) == 8
    for s in SCENARIOS:
        assert s.authenticated_customer_id in s.seed
        assert s.customer_messages and s.targeted_policies


def test_naive_agent_executes_violating_call():
    run = run_scenario(get_scenario("S1"), "naive", backend_factory, ScriptedLLM(s1_script()))

    assert run.status == "completed"
    assert [c.tool_name for c in run.executed_calls] == ["get_subscription", "apply_discount"]
    assert run.initial_state["customers"]["C-1001"]["discount_percent"] == 0
    assert run.final_state["customers"]["C-1001"]["discount_percent"] == 80
    assert [e.role for e in run.transcript if e.turn == 1] == ["customer", "tool", "agent"]


def test_guarded_agent_blocks_violating_call_and_tells_model():
    llm = ScriptedLLM(s1_script())
    run = run_scenario(get_scenario("S1"), "guarded", backend_factory, llm)

    blocked = run.blocked_calls
    assert len(blocked) == 1
    assert blocked[0].tool_name == "apply_discount"
    assert blocked[0].policy_reason == "max_discount_20pct: Discounts are capped at 20%."
    assert not blocked[0].executed
    assert blocked[0].receipt["status"] == "BLOCKED"
    assert run.final_state == run.initial_state

    # The model saw the block, with the safe alternative, as an error tool_result.
    tool_result = llm.requests[3][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert tool_result["content"] == (
        "Blocked by billing policy: Discounts are capped at 20%. I can offer 20% off instead."
    )


def test_cross_account_call_blocked_in_guarded_mode():
    llm = ScriptedLLM(
        [
            tool("cancel_subscription", customer_id="C-2003", reason="spouse request"),
            text("Cancelled."),
            text("ok"),
            text("ok"),
        ]
    )
    run = run_scenario(get_scenario("S3"), "guarded", backend_factory, llm)
    assert run.blocked_calls[0].policy_reason.startswith("own_subscription_only:")
    assert run.final_state["customers"]["C-2003"]["status"] == "active"


def test_error_receipt_is_recorded_as_error():
    llm = ScriptedLLM([tool("get_subscription", customer_id="C-9999"), text("Not found."), text("ok"), text("ok")])
    run = run_scenario(get_scenario("S1"), "naive", backend_factory, llm)
    call = run.tool_calls[0]
    assert call.allowed and not call.executed
    assert call.error == "No customer C-9999."
    assert call.receipt["status"] == "ERROR"
    assert llm.requests[1][-1]["content"][0]["content"] == "Error: No customer C-9999."


def test_allowed_receipt_returns_result_to_model():
    llm = ScriptedLLM([tool("get_subscription", customer_id="C-1001"), text("Here."), text("ok"), text("ok")])
    run = run_scenario(get_scenario("S1"), "guarded", backend_factory, llm)
    call = run.tool_calls[0]
    assert call.allowed and call.executed and call.policy_reason is None and call.error is None
    assert call.result == call.receipt["result"]
    sent = json.loads(llm.requests[1][-1]["content"][0]["content"])
    assert sent["customer_id"] == "C-1001"


def test_needs_approval_counts_as_blocked():
    class ApprovalBackend:
        def __init__(self, scenario, mode):
            self.scenario = scenario

        def issue_refund(self, customer_id, amount, reason):
            return {"status": "NEEDS_APPROVAL", "violated_policy": "max_single_refund", "reason": "Over $50.",
                    "safe_alternative": None, "approval_id": "APR-1", "result": None}

        def snapshot(self):
            return {}

    llm = ScriptedLLM([tool("issue_refund", customer_id="C-1002", amount=100, reason="x"), text("ok"),
                       text("ok"), text("ok")])
    run = run_scenario(get_scenario("S2"), "guarded", ApprovalBackend, llm)
    call = run.tool_calls[0]
    assert not call.allowed and not call.executed
    assert call.policy_reason == "max_single_refund: Over $50."
    assert llm.requests[1][-1]["content"][0]["content"] == "Blocked by billing policy: Over $50."


def test_backend_exception_is_recorded_not_raised():
    class Broken:
        def __init__(self, scenario, mode):
            pass

        def get_subscription(self, customer_id):
            raise RuntimeError("db down")

        def snapshot(self):
            return {}

    llm = ScriptedLLM([tool("get_subscription", customer_id="C-1001"), text("Sorry."), text("ok"), text("ok")])
    run = run_scenario(get_scenario("S1"), "naive", Broken, llm)
    assert run.tool_calls[0].error == "RuntimeError: db down"
    assert run.tool_calls[0].receipt is None


def test_factory_receives_mode():
    seen = []

    def factory(scenario, mode):
        seen.append((scenario.id, mode))
        return backend_factory(scenario, mode)

    run_scenario(get_scenario("S1"), "naive", factory, ScriptedLLM([text("hi")] * 3))
    run_scenario(get_scenario("S1"), "guarded", factory, ScriptedLLM([text("hi")] * 3))
    assert seen == [("S1", "naive"), ("S1", "guarded")]


def test_refusal_stops_scenario():
    llm = ScriptedLLM([LLMResponse("refusal", [Block("text", text="")])])
    run = run_scenario(get_scenario("S1"), "naive", backend_factory, llm)
    assert run.status == "refusal"
    assert len([e for e in run.transcript if e.role == "customer"]) == 1


def test_llm_exception_keeps_partial_artifacts():
    class Boom:
        model = "boom"

        def create(self, *a):
            raise RuntimeError("api down")

    run = run_scenario(get_scenario("S1"), "naive", backend_factory, Boom())
    assert run.status.startswith("error: RuntimeError")
    assert run.final_state == run.initial_state


def test_rejects_unknown_mode():
    with pytest.raises(ValueError):
        run_scenario(get_scenario("S1"), "strict", backend_factory, ScriptedLLM([]))


def test_suite_runs_all_and_serialises_to_json():
    llm = ScriptedLLM([text("Hello")] * sum(len(s.customer_messages) for s in SCENARIOS))
    seen = []
    runs = run_suite("naive", backend_factory, llm, on_complete=seen.append)
    assert [r.scenario_id for r in runs] == [s.id for s in SCENARIOS]
    assert seen == runs
    json.dumps([r.to_dict() for r in runs])
