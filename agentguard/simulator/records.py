"""Run artifacts handed to the evaluator (Shubhi).

Everything here serialises to plain JSON via ``to_dict()``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

AgentMode = Literal["naive", "guarded"]


@dataclass
class ToolCallRecord:
    """One tool call the agent attempted."""

    turn: int
    tool_use_id: str
    tool_name: str
    arguments: dict[str, Any]
    # False only when the policy engine blocked the call (guarded mode).
    allowed: bool
    # True when the backend method actually ran (and may have changed state).
    executed: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    policy_reason: str | None = None


@dataclass
class TranscriptEntry:
    turn: int
    role: Literal["customer", "agent", "tool"]
    text: str


@dataclass
class ScenarioRun:
    scenario_id: str
    attack_type: str
    mode: AgentMode
    model: str
    authenticated_customer_id: str
    targeted_policies: list[str]
    initial_state: dict[str, Any]
    final_state: dict[str, Any]
    transcript: list[TranscriptEntry] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    # "completed", "refusal", "max_tool_iterations" or "error: <message>"
    status: str = "completed"

    @property
    def executed_calls(self) -> list[ToolCallRecord]:
        return [c for c in self.tool_calls if c.executed]

    @property
    def blocked_calls(self) -> list[ToolCallRecord]:
        return [c for c in self.tool_calls if not c.allowed]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
