from __future__ import annotations

import json
from pathlib import Path

from agentguard.analytics import scoreboard_report, write_scoreboard
from agentguard.cli import main
from agentguard.simulator import SCENARIOS


def valid_trace(scenario_id: str, naive: float, guarded: float) -> dict:
    return {
        "scenario_id": scenario_id,
        "prompt": "fixture prompt",
        "tool_calls": [{
            "tool": "issue_refund",
            "args": {"amount": 15},
            "policy_result": {"status": "BLOCKED", "violated_policy": "max_refund_50_usd"},
        }],
        "unprotected_loss": naive,
        "protected_loss": guarded,
    }


def write_fixture_pair(runs: Path, scenario_id: str, *, naive: float, guarded: float, unauthorized_modes: tuple[str, ...] = ()) -> None:
    actor_id = "C-1001"
    for mode in ("naive", "guarded"):
        unauthorized = mode in unauthorized_modes
        owner_id = "C-1002" if unauthorized else actor_id
        sub_id = f"SUB-{owner_id}"
        executed = mode == "naive"
        status = "ALLOWED" if executed else "BLOCKED"
        receipt = {
            "receipt_version": 1,
            "mode": mode,
            "status": status,
            "tool": "issue_refund",
            "args": {"amount": 15},
            "actor_id": actor_id,
            "sub_id": sub_id,
            "checks": [],
            "violated_policy": None if status == "ALLOWED" else "max_refund_50_usd",
            "reason": "" if status == "ALLOWED" else "Refund exceeds limit",
            "safe_alternative": None,
            "approval_id": None,
            "executed": executed,
            "money": {"refund_usd": 15.0 if executed else 0.0, "discount_value_12m_usd": 0.0},
            "result": None,
        }
        subscription = {"id": sub_id, "customer_id": owner_id, "plan_id": "PLAN-FIXTURE", "status": "active", "discount_percent": 0}
        run = {
            "scenario_id": scenario_id,
            "attack_type": "fixture_only",
            "mode": mode,
            "model": "fixture-only",
            "authenticated_customer_id": actor_id,
            "targeted_policies": [],
            "initial_state": {"subscriptions": {sub_id: subscription}, "plans": {}, "refunds": []},
            "final_state": {"subscriptions": {sub_id: subscription}, "plans": {}, "refunds": []},
            "transcript": [],
            "tool_calls": [{
                "turn": 1,
                "tool_use_id": f"fixture-{scenario_id}-{mode}",
                "tool_name": "issue_refund",
                "arguments": {"amount": 15},
                "allowed": executed,
                "executed": executed,
                "receipt": receipt,
            }],
            "status": "completed",
        }
        (runs / f"{scenario_id}.{mode}.json").write_text(json.dumps(run), encoding="utf-8")


def write_fixture_scenario(runs: Path, scenario_id: str, naive: float, guarded: float, *, unauthorized_modes: tuple[str, ...] = ()) -> None:
    write_fixture_pair(runs, scenario_id, naive=naive, guarded=guarded, unauthorized_modes=unauthorized_modes)
    (runs / f"{scenario_id}.trace.json").write_text(
        json.dumps(valid_trace(scenario_id, naive, guarded)), encoding="utf-8"
    )


def test_scoreboard_totals_include_signed_deltas_and_receipt_unauthorized_counts(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    for index, scenario in enumerate(SCENARIOS):
        write_fixture_scenario(
            runs, scenario.id, 10 + index, 2,
            unauthorized_modes=("naive",) if index == 0 else (),
        )
    output, report = write_scoreboard(runs, tmp_path / "scoreboard.html")
    assert report["complete"]
    assert len(report["rows"]) == 8
    assert report["totals"] == {
        "naive_loss": 108.0,
        "guarded_loss": 16.0,
        "damage_prevented": 92.0,
        "unauthorized_actions": 1,
    }
    assert report["rows"][0]["unauthorized_actions"] == 1
    page = output.read_text(encoding="utf-8")
    assert "Total damage prevented" in page
    assert "Unauthorized actions" in page


def test_aggregate_analyze_cli_totals_match_scoreboard(tmp_path, capsys):
    runs = tmp_path / "runs"
    runs.mkdir()
    for index, scenario in enumerate(SCENARIOS):
        write_fixture_scenario(runs, scenario.id, 10 + index, 2)
    expected = scoreboard_report(runs)["totals"]
    code = main(["analyze", str(runs)])
    actual = json.loads(capsys.readouterr().out)["analytics"]["totals"]
    assert code == 0
    assert actual == expected


def test_missing_invalid_and_unexpected_traces_are_visible_and_not_counted(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    write_fixture_scenario(runs, "S1", 9, 0)
    (runs / "S2.trace.json").write_text("{bad json", encoding="utf-8")
    (runs / "S9.trace.json").write_text(json.dumps(valid_trace("S9", 200, 0)), encoding="utf-8")
    output, report = write_scoreboard(runs, tmp_path / "scoreboard.html")
    page = output.read_text(encoding="utf-8")
    assert not report["complete"]
    assert report["totals"] == {
        "naive_loss": 9.0,
        "guarded_loss": 0.0,
        "damage_prevented": 9.0,
        "unauthorized_actions": 0,
    }
    assert sum(row["status"] == "missing" for row in report["rows"]) == 7
    assert "INVALID:" in page and "MISSING" in page and "UNEXPECTED SCENARIO" in page


def test_trace_without_paired_raw_receipts_is_not_reported_as_zero_actions(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "S1.trace.json").write_text(json.dumps(valid_trace("S1", 9, 0)), encoding="utf-8")

    report = scoreboard_report(runs)

    assert not report["complete"]
    assert report["totals"]["unauthorized_actions"] == 0
    assert report["rows"][0]["status"] == "missing"
    assert "invalid paired run receipts" in report["extras"][0]["status"]


def test_cli_scoreboard_returns_failure_when_results_are_incomplete(tmp_path, capsys):
    output = tmp_path / "scoreboard.html"
    code = main(["scoreboard", str(tmp_path / "missing-runs"), "--output", str(output)])
    captured = capsys.readouterr()
    assert code == 1
    assert output.exists()
    assert "0/8 valid scenarios" in captured.out
    assert "missing" in captured.err


def test_scoreboard_marks_unrepresentable_aggregate_as_invalid(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    for index, scenario in enumerate(SCENARIOS):
        loss = 10**400 if index == 0 else 10
        write_fixture_scenario(runs, scenario.id, loss, 0)

    report = scoreboard_report(runs)

    assert not report["complete"]
    assert report["rows"][0]["status"] == "invalid: aggregate total outside finite numeric range"
    assert report["totals"] == {
        "naive_loss": 70.0,
        "guarded_loss": 0.0,
        "damage_prevented": 70.0,
        "unauthorized_actions": 0,
    }
