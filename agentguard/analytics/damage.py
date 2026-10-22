"""Damage delta calculation using only the two loss values in a trace."""
from __future__ import annotations

import math
from typing import Any

from .trace import TraceValidationError, validate_trace


def _calculate_validated_damage_delta(data: dict[str, Any]) -> dict[str, Any]:
    """Calculate from an already validated defensive trace copy."""
    unprotected = data["unprotected_loss"]
    protected = data["protected_loss"]
    try:
        delta = unprotected - protected
        if type(delta) is float and not math.isfinite(delta):
            raise TraceValidationError("calculated damage_delta is outside the finite numeric range")
    except OverflowError as exc:
        raise TraceValidationError("calculated damage_delta is outside the finite numeric range") from exc
    if delta > 0:
        interpretation = "protected_loss_is_lower"
    elif delta < 0:
        interpretation = "protected_loss_is_higher"
    else:
        interpretation = "loss_values_are_equal"
    return {
        "scenario_id": data["scenario_id"],
        "unprotected_loss": unprotected,
        "protected_loss": protected,
        "damage_delta": delta,
        "formula": "unprotected_loss - protected_loss",
        "interpretation": interpretation,
    }


def calculate_damage_delta(trace: dict[str, Any]) -> dict[str, Any]:
    """Return unprotected_loss minus protected_loss.

    A positive delta means the trace reports a lower loss in the protected
    case by that amount; a negative delta means the protected value is higher;
    zero means the values are equal. No currency or causal interpretation is
    added because the trace contract does not provide either.
    """
    return _calculate_validated_damage_delta(validate_trace(trace))
