import json

import pytest

from agentguard.simulator import SCENARIOS, LLMResponse, get_scenario, run_scenario, run_suite

from .fakes import Block, CapPolicy, ScriptedLLM, backend_factory, text, tool


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
    run = run_scenario(get_scenario("S1"), "guarded", backend_factory, llm, CapPolicy())

    blocked = run.blocked_calls
    assert len(blocked) == 1
    assert blocked[0].tool_name == "apply_discount"
    assert blocked[0].policy_reason == "max_discount"
    assert not blocked[0].executed
    assert run.final_state == run.initial_state

    # The model saw the block as an error tool_result.
    tool_result = llm.requests[3][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "blocked by billing policy" in tool_result["content"]


def test_cross_account_call_blocked_in_guarded_mode():
    llm = ScriptedLLM(
        [
            tool("cancel_subscription", customer_id="C-2003", reason="spouse request"),
            text("Cancelled."),
            text("ok"),
            text("ok"),
        ]
    )
    run = run_scenario(get_scenario("S3"), "guarded", backend_factory, llm, CapPolicy())
    assert run.blocked_calls[0].policy_reason == "account_ownership"
    assert run.final_state["customers"]["C-2003"]["status"] == "active"


def test_backend_error_is_recorded_not_raised():
    llm = ScriptedLLM([tool("get_subscription", customer_id="C-9999"), text("Not found."), text("ok"), text("ok")])
    run = run_scenario(get_scenario("S1"), "naive", backend_factory, llm)
    call = run.tool_calls[0]
    assert call.allowed and not call.executed
    assert "unknown customer" in call.error


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


def test_guarded_requires_policy_engine():
    with pytest.raises(ValueError):
        run_scenario(get_scenario("S1"), "guarded", backend_factory, ScriptedLLM([]))


def test_suite_runs_all_and_serialises_to_json():
    llm = ScriptedLLM([text("Hello")] * sum(len(s.customer_messages) for s in SCENARIOS))
    seen = []
    runs = run_suite("naive", backend_factory, llm, on_complete=seen.append)
    assert [r.scenario_id for r in runs] == [s.id for s in SCENARIOS]
    assert seen == runs
    json.dumps([r.to_dict() for r in runs])
