from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentguard.analytics import TraceValidationError, calculate_damage_delta, load_trace, replay_trace
from agentguard.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "execution_traces"


def test_contract_fixture_replays_in_recorded_order_and_is_deterministic():
    trace = load_trace(FIXTURES / "micro_refund_split_01.json")
    first = replay_trace(trace)
    second = replay_trace(trace)
    assert first == second
    assert first["scenario_id"] == "micro_refund_split_01"
    assert first["summary"] == {"total": 2, "allowed": 1, "blocked": 1}
    assert [call["sequence"] for call in first["replayed_calls"]] == [1, 2]
    assert first["replayed_calls"][1]["policy_result"] == {
        "status": "BLOCKED", "violated_policy": "max_daily_refund_cap"
    }


def test_replay_does_not_mutate_fixture_data():
    trace = load_trace(FIXTURES / "micro_refund_split_01.json")
    before = json.loads(json.dumps(trace))
    replay_trace(trace)
    assert trace == before


def test_damage_delta_positive_means_protected_loss_is_lower():
    trace = load_trace(FIXTURES / "micro_refund_split_01.json")
    result = calculate_damage_delta(trace)
    assert result["damage_delta"] == 60.0
    assert result["formula"] == "unprotected_loss - protected_loss"
    assert result["interpretation"] == "protected_loss_is_lower"


def test_damage_delta_zero_means_equal_reported_values():
    result = calculate_damage_delta(load_trace(FIXTURES / "equal_losses.json"))
    assert result["damage_delta"] == 0.0
    assert result["interpretation"] == "loss_values_are_equal"


def test_negative_damage_delta_means_protected_value_is_higher():
    result = calculate_damage_delta(load_trace(FIXTURES / "protected_loss_higher.json"))
    assert result["damage_delta"] == -5.0
    assert result["interpretation"] == "protected_loss_is_higher"


@pytest.mark.parametrize(
    ("fixture", "message"),
    [
        ("invalid_missing_loss.json", "missing required field.*protected_loss"),
        ("invalid_status.json", "expected 'ALLOWED' or 'BLOCKED'"),
        ("invalid_boolean_loss.json", "booleans are not numbers"),
    ],
)
def test_malformed_static_fixtures_fail_clearly(fixture: str, message: str):
    with pytest.raises(TraceValidationError, match=message):
        load_trace(FIXTURES / fixture)


def test_unknown_fields_are_not_silently_ignored():
    trace = load_trace(FIXTURES / "equal_losses.json")
    trace["schema_version"] = "1"
    with pytest.raises(TraceValidationError, match="unexpected field.*schema_version"):
        replay_trace(trace)


def test_cli_run_emits_machine_readable_combined_report(capsys):
    code = main(["run", str(FIXTURES / "micro_refund_split_01.json")])
    captured = capsys.readouterr()
    assert code == 0
    report = json.loads(captured.out)
    assert report["replay"]["summary"]["blocked"] == 1
    assert report["analytics"]["damage_delta"] == 60.0
    assert captured.err == ""


def test_cli_text_output_and_output_file(tmp_path: Path, capsys):
    output = tmp_path / "report.txt"
    code = main(["analyze", str(FIXTURES / "equal_losses.json"), "--format", "text", "--output", str(output)])
    assert code == 0
    assert "loss_values_are_equal" in output.read_text(encoding="utf-8")
    assert capsys.readouterr().out == ""


def test_cli_malformed_trace_returns_error_code_and_message(capsys):
    code = main(["analyze", str(FIXTURES / "invalid_missing_loss.json")])
    captured = capsys.readouterr()
    assert code == 1
    assert "missing required field" in captured.err
    assert captured.out == ""


def test_cli_missing_file_returns_error_code(capsys, tmp_path: Path):
    code = main(["replay", str(tmp_path / "does-not-exist.json")])
    assert code == 1
    assert "does-not-exist.json" in capsys.readouterr().err


def test_cli_json_output_file_is_machine_readable(tmp_path: Path, capsys):
    output = tmp_path / "report.json"
    code = main(["analyze", str(FIXTURES / "micro_refund_split_01.json"), "--output", str(output)])
    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["analytics"]["damage_delta"] == 60.0
    assert capsys.readouterr().out == ""


def test_cli_invalid_usage_uses_argparse_exit_code(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_damage_delta_that_overflows_float_is_reported_clearly():
    trace = load_trace(FIXTURES / "float_delta_overflow.json")
    with pytest.raises(TraceValidationError, match="calculated damage_delta"):
        calculate_damage_delta(trace)
