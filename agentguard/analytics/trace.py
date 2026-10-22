"""Loader and strict validator for the frozen Execution Trace JSON shape.

The supplied contract has no schema_version field. This loader validates
that exact unversioned shape and rejects unknown fields rather than silently
guessing a version or filling in missing data.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any


class TraceValidationError(ValueError):
    """A trace is malformed or does not match the frozen JSON contract."""


_TRACE_FIELDS = {"scenario_id", "prompt", "tool_calls", "unprotected_loss", "protected_loss"}
_CALL_FIELDS = {"tool", "args", "policy_result"}
_POLICY_FIELDS = {"status", "violated_policy"}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting repeated keys at every depth."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TraceValidationError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{path}: object keys must be strings")
    missing = sorted(expected - value.keys())
    extra = sorted(value.keys() - expected)
    if missing:
        raise TraceValidationError(f"{path}: missing required field(s): {', '.join(missing)}")
    if extra:
        raise TraceValidationError(f"{path}: unexpected field(s): {', '.join(extra)}")


def _json_value(value: Any, path: str) -> None:
    """Ensure args contain only JSON values, including finite numbers."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise TraceValidationError(f"{path}: number must be finite")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _json_value(item, f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TraceValidationError(f"{path}: object keys must be strings")
            _json_value(item, f"{path}.{key}")
        return
    raise TraceValidationError(f"{path}: value is not JSON-compatible")


def validate_trace(data: Any) -> dict[str, Any]:
    """Validate and return a defensive copy of one contract-shaped trace."""
    if type(data) is not dict:
        raise TraceValidationError("$: expected a JSON object")
    _keys(data, _TRACE_FIELDS, "$")

    for field in ("scenario_id", "prompt"):
        if type(data[field]) is not str:
            raise TraceValidationError(f"$.{field}: expected a string")
    if not data["scenario_id"]:
        raise TraceValidationError("$.scenario_id: must not be empty")

    calls = data["tool_calls"]
    if type(calls) is not list:
        raise TraceValidationError("$.tool_calls: expected an array")
    for index, call in enumerate(calls):
        path = f"$.tool_calls[{index}]"
        if type(call) is not dict:
            raise TraceValidationError(f"{path}: expected an object")
        _keys(call, _CALL_FIELDS, path)
        if type(call["tool"]) is not str or not call["tool"]:
            raise TraceValidationError(f"{path}.tool: expected a non-empty string")
        if type(call["args"]) is not dict:
            raise TraceValidationError(f"{path}.args: expected an object")
        _json_value(call["args"], f"{path}.args")

        policy = call["policy_result"]
        policy_path = f"{path}.policy_result"
        if type(policy) is not dict:
            raise TraceValidationError(f"{policy_path}: expected an object")
        _keys(policy, _POLICY_FIELDS, policy_path)
        status = policy["status"]
        if type(status) is not str or status not in ("ALLOWED", "BLOCKED"):
            raise TraceValidationError(f"{policy_path}.status: expected 'ALLOWED' or 'BLOCKED'")
        violated = policy["violated_policy"]
        if status == "BLOCKED" and (type(violated) is not str or not violated):
            raise TraceValidationError(f"{policy_path}.violated_policy: BLOCKED requires a non-empty string")
        if status == "ALLOWED" and violated is not None:
            raise TraceValidationError(f"{policy_path}.violated_policy: ALLOWED requires null")

    for field in ("unprotected_loss", "protected_loss"):
        value = data[field]
        if type(value) not in (int, float):
            raise TraceValidationError(f"$.{field}: expected a number (booleans are not numbers here)")
        if value < 0:
            raise TraceValidationError(f"$.{field}: number must be non-negative")
        # Integers are exact finite Python values; converting a very large int
        # to float here would itself overflow and incorrectly reject it.
        if type(value) is float and not math.isfinite(value):
            raise TraceValidationError(f"$.{field}: number must be finite")

    try:
        _json_value(data, "$")
        return copy.deepcopy(data)
    except RecursionError as exc:
        raise TraceValidationError("$: trace nesting exceeds the supported depth") from exc


def _reject_constant(value: str) -> None:
    raise TraceValidationError(f"invalid JSON numeric constant {value}")


def load_trace(path: str | Path) -> dict[str, Any]:
    """Load and validate a UTF-8 JSON trace from disk.

    Parser limits (including oversized integer tokens and excessive nesting)
    are reported as TraceValidationError instead of exposing a traceback.
    """
    trace_path = Path(path)
    try:
        with trace_path.open("r", encoding="utf-8") as stream:
            data = json.load(stream, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except TraceValidationError as exc:
        raise TraceValidationError(f"{trace_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise TraceValidationError(f"{trace_path}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    except UnicodeDecodeError as exc:
        raise TraceValidationError(f"{trace_path}: file is not valid UTF-8: {exc}") from exc
    except (ValueError, RecursionError) as exc:
        raise TraceValidationError(f"{trace_path}: invalid or excessively complex JSON: {exc}") from exc
    try:
        return validate_trace(data)
    except RecursionError as exc:
        raise TraceValidationError(f"{trace_path}: trace nesting exceeds the supported depth") from exc
