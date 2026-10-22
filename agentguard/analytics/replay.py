"""Deterministic replay of recorded decisions without executing live tools."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .trace import load_trace, validate_trace


def _replay_validated_trace(data: dict[str, Any]) -> dict[str, Any]:
    calls = []
    allowed = blocked = 0
    for index, call in enumerate(data["tool_calls"], start=1):
        policy_result = dict(call["policy_result"])
        if policy_result["status"] == "ALLOWED":
            allowed += 1
        else:
            blocked += 1
        calls.append({
            "sequence": index,
            "tool": call["tool"],
            "args": call["args"],
            "policy_result": policy_result,
        })
    return {
        "scenario_id": data["scenario_id"],
        "replayed_calls": calls,
        "summary": {"total": len(calls), "allowed": allowed, "blocked": blocked},
    }


def replay_trace(trace: dict[str, Any] | str | Path) -> dict[str, Any]:
    """Replay the ordered calls and recorded policy decisions from a trace.

    This reproduces the trace's recorded decision sequence. It deliberately
    does not call tools or recompute policies: the frozen trace has no backend
    state or policy configuration with which to do so safely.
    """
    data = load_trace(trace) if isinstance(trace, (str, Path)) else validate_trace(trace)
    return _replay_validated_trace(data)
