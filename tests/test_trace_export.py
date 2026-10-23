from __future__ import annotations

import copy
from pathlib import Path

import pytest

from agentguard.analytics import (
    TraceValidationError,
    calculate_state_loss,
    export_trace_from_run_dir,
    load_trace,
    validate_trace,
    export_trace,
)
from agentguard.simulator import load_run_dir
from agentguard.simulator import get_scenario

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "run_serialization" / "handmade-c1-s1"


def _fixture_runs():
    return load_run_dir(FIXTURE_DIR)


def test_load_run_dir_reconstructs_fixture_pair_and_full_receipt():
    runs = _fixture_runs()

    assert set(runs) == {("S1", "naive"), ("S1", "guarded")}
    guarded = runs[("S1", "guarded")]
    assert guarded.tool_calls[0].receipt["status"] == "BLOCKED"
    assert guarded.tool_calls[0].receipt["args"]["percent"] == 80


def test_state_loss_uses_new_refund_ids_and_final_plan_price():
    naive = _fixture_runs()[("S1", "naive")]
    # 12.34 new refund + $29.99 * 10% * 12 = $48.33 total after rounding.
    assert calculate_state_loss(naive.initial_state, naive.final_state) == 48.33

    initial = copy.deepcopy(naive.initial_state)
    # A pre-existing refund ID is not new, even if other serialized fields differ.
    initial["refunds"][0]["amount"] = 999
    assert calculate_state_loss(initial, naive.final_state) == 48.33


@pytest.mark.parametrize("plan_id", ["PLAN-PREMIUM_MONTHLY", "PLAN-PRO"])
def test_state_loss_looks_up_monthly_price_using_subscription_plan_id(plan_id):
    naive = _fixture_runs()[("S1", "naive")]
    initial = copy.deepcopy(naive.initial_state)
    final = copy.deepcopy(naive.final_state)
    fixture_plan_id = "PLAN-PREMIUM_MONTHLY"

    for snapshot in (initial, final):
        plan = snapshot["plans"].pop(fixture_plan_id)
        plan["id"] = plan_id
        snapshot["plans"][plan_id] = plan
        snapshot["subscriptions"]["SUB-C-1001"]["plan_id"] = plan_id

    assert calculate_state_loss(initial, final) == 48.33


def test_cancelled_subscription_has_zero_future_discount_exposure():
    naive = _fixture_runs()[("S1", "naive")]
    final = copy.deepcopy(naive.final_state)
    final["subscriptions"]["SUB-C-1001"]["status"] = "cancelled"

    assert calculate_state_loss(naive.initial_state, final) == 12.34


def test_export_writes_and_validates_s1_trace_in_temporary_output(tmp_path):
    output_dir = tmp_path / "fixture-output"
    trace_path = export_trace_from_run_dir(FIXTURE_DIR, get_scenario("S1"), output_dir=output_dir)

    assert trace_path == output_dir / "S1.trace.json"
    trace = load_trace(trace_path)
    assert trace == validate_trace(trace)
    assert set(trace) == {
        "scenario_id", "prompt", "tool_calls", "unprotected_loss", "protected_loss"
    }
    assert trace["scenario_id"] == "S1"
    assert trace["unprotected_loss"] == 48.33
    assert trace["protected_loss"] == 0
    assert not (FIXTURE_DIR / "S1.trace.json").exists()


def test_prompt_uses_two_newlines_and_calls_use_receipt_args(tmp_path):
    trace_path = export_trace_from_run_dir(FIXTURE_DIR, get_scenario("S1"), output_dir=tmp_path)
    trace = load_trace(trace_path)
    guarded = _fixture_runs()[("S1", "guarded")]
    receipt = guarded.tool_calls[0].receipt

    assert trace["prompt"] == "\n\n".join(get_scenario("S1").customer_messages)
    assert trace["tool_calls"][0]["args"] == receipt["args"]


@pytest.mark.parametrize(
    ("status", "violated_policy", "executed", "expected"),
    [
        ("ALLOWED", None, True, "ALLOWED"),
        ("BLOCKED", "max_discount_20pct", False, "BLOCKED"),
        ("NEEDS_APPROVAL", "approval_required", False, "BLOCKED"),
        ("ERROR", "invalid_arguments:BAD_AMOUNT", False, "BLOCKED"),
    ],
)
def test_contract_v2_receipt_status_mapping(status, violated_policy, executed, expected, tmp_path):
    guarded = _fixture_runs()[("S1", "guarded")]
    receipt = guarded.tool_calls[0].receipt
    receipt["status"] = status
    receipt["violated_policy"] = violated_policy
    receipt["executed"] = executed
    trace = export_trace(get_scenario("S1"), _fixture_runs()[("S1", "naive")], guarded)

    assert trace["tool_calls"][0]["policy_result"]["status"] == expected
    assert trace["tool_calls"][0]["policy_result"]["violated_policy"] == violated_policy
    assert validate_trace(trace) == trace


def test_export_rejects_discount_increase_without_plan_monthly_price():
    naive = _fixture_runs()[("S1", "naive")]
    final = copy.deepcopy(naive.final_state)
    del final["plans"]["PLAN-PREMIUM_MONTHLY"]["monthly_price"]

    with pytest.raises(TraceValidationError, match=r"final_state\.plans\.PLAN-PREMIUM_MONTHLY\.monthly_price"):
        calculate_state_loss(naive.initial_state, final)


def test_run_directory_missing_pair_is_reported_clearly(tmp_path):
    naive = _fixture_runs()[("S1", "naive")]
    from agentguard.simulator import save_run

    save_run(naive, tmp_path)
    with pytest.raises(TraceValidationError, match="missing the S1 guarded run"):
        export_trace_from_run_dir(tmp_path, get_scenario("S1"), output_dir=tmp_path / "out")
