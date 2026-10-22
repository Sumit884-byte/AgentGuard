"""Validated static execution-trace replay and loss-delta analysis."""
from .damage import calculate_damage_delta
from .replay import replay_trace
from .trace import TraceValidationError, load_trace, validate_trace

__all__ = ["TraceValidationError", "calculate_damage_delta", "load_trace", "replay_trace", "validate_trace"]
