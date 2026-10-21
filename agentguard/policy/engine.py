"""The policy engine: evaluate a tool call against YAML rules.

Uses restricted Python eval() — not simpleeval — so the expression
language is plain Python and there's no library API to fight.

Trust model: rule conditions come from the user's own YAML policy file,
not from untrusted input. Same trust as a pytest file.
"""
from __future__ import annotations

from pathlib import Path

from .cumulative import SessionState
from .parser import load_policies
from .schema import PolicyResult, PolicyRule, ToolCallEvent


_SAFE_BUILTINS = {
    "len": len, "abs": abs, "min": min, "max": max,
    "int": int, "float": float, "str": str, "bool": bool,
    "True": True, "False": False, "None": None,
}


def _safe_eval(expr: str, context: dict) -> bool:
    return bool(eval(expr, {"__builtins__": _SAFE_BUILTINS}, context))


class PolicyEngine:
    def __init__(self, rules: list[PolicyRule]) -> None:
        self.rules = rules

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PolicyEngine":
        return cls(load_policies(path))

    def evaluate(self, event: ToolCallEvent, state: SessionState) -> PolicyResult:
        context = state.build_context(event)
        applicable = [r for r in self.rules if event.tool_name in r.applies_to]
        for rule in applicable:
            try:
                passed = _safe_eval(rule.condition, context)
            except Exception as exc:
                return PolicyResult(
                    status="BLOCKED",
                    violated_policy=rule.name,
                    detail=f"Policy {rule.name!r} could not be evaluated: {exc!r}",
                )
            if not passed:
                return PolicyResult(
                    status="BLOCKED",
                    violated_policy=rule.name,
                    detail=rule.violation_detail or f"Rule {rule.name!r} failed",
                )
        state.apply_mutation(event)
        return PolicyResult(status="ALLOWED")
