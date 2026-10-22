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


def test_duplicate_top_level_protected_loss_key_is_rejected(tmp_path: Path):
    trace_path = tmp_path / "duplicate.json"
    trace_path.write_text(
        '{"scenario_id":"x","prompt":"p","tool_calls":[],"unprotected_loss":1,'
        '"protected_loss":0,"protected_loss":0}',
        encoding="utf-8",
    )
    with pytest.raises(TraceValidationError, match="duplicate JSON key.*protected_loss"):
        load_trace(trace_path)


@pytest.mark.parametrize(
    ("status", "violated_policy", "message"),
    [
        ("BLOCKED", None, "BLOCKED requires a non-empty string"),
        ("ALLOWED", "some_policy", "ALLOWED requires null"),
    ],
)
def test_policy_result_fields_must_match_status(status: str, violated_policy: str | None, message: str):
    trace = load_trace(FIXTURES / "micro_refund_split_01.json")
    trace["tool_calls"][0]["policy_result"] = {
        "status": status,
        "violated_policy": violated_policy,
    }
    with pytest.raises(TraceValidationError, match=message):
        replay_trace(trace)


@pytest.mark.parametrize("field", ["unprotected_loss", "protected_loss"])
@pytest.mark.parametrize("value", [-1, -0.01])
def test_negative_loss_values_are_rejected(field: str, value: int | float):
    trace = load_trace(FIXTURES / "equal_losses.json")
    trace[field] = value
    with pytest.raises(TraceValidationError, match=f"{field}.*non-negative"):
        calculate_damage_delta(trace)


def test_cli_oversized_integer_parser_error_is_concise(tmp_path: Path, capsys):
    trace_path = tmp_path / "oversized_integer.json"
    trace_path.write_text(
        '{"scenario_id":"x","prompt":"p","tool_calls":[],"unprotected_loss":'
        + "9" * 5000
        + ',"protected_loss":0}',
        encoding="utf-8",
    )
    code = main(["analyze", str(trace_path)])
    captured = capsys.readouterr()
    assert code == 1
    assert "invalid or excessively complex JSON" in captured.err
    assert "Traceback" not in captured.err


def test_cli_deeply_nested_json_parser_error_is_concise(tmp_path: Path, capsys):
    trace_path = tmp_path / "deeply_nested.json"
    trace_path.write_text(
        '{"scenario_id":"x","prompt":"p","tool_calls":[{"tool":"inspect",'
        '"args":{"nested":' + "[" * 2000 + "0" + "]" * 2000 + '},'
        '"policy_result":{"status":"ALLOWED","violated_policy":null}}],'
        '"unprotected_loss":0,"protected_loss":0}',
        encoding="utf-8",
    )
    code = main(["analyze", str(trace_path)])
    captured = capsys.readouterr()
    assert code == 1
    assert any(message in captured.err for message in (
        "invalid JSON", "excessively complex JSON", "nesting exceeds the supported depth"
    ))
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("status", "violated_policy", "message"),
    [
        (1, None, "status: expected 'ALLOWED' or 'BLOCKED'"),
        ("BLOCKED", True, "BLOCKED requires a non-empty string"),
    ],
)
def test_policy_result_types_are_validated(status, violated_policy, message: str):
    trace = load_trace(FIXTURES / "micro_refund_split_01.json")
    trace["tool_calls"][0]["policy_result"] = {
        "status": status,
        "violated_policy": violated_policy,
    }
    with pytest.raises(TraceValidationError, match=message):
        replay_trace(trace)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_json_losses_are_rejected(tmp_path: Path, literal: str):
    trace_path = tmp_path / "non_finite.json"
    trace_path.write_text(
        '{"scenario_id":"x","prompt":"p","tool_calls":[],"unprotected_loss":'
        + literal
        + ',"protected_loss":0}',
        encoding="utf-8",
    )
    with pytest.raises(TraceValidationError):
        load_trace(trace_path)
