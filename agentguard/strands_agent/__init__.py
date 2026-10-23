"""Strands agent on Bedrock as the MCP client of the billing servers (B2).

Needs the optional dependencies: ``pip install -e ".[agent]"``.
"""

from .agent import DEFAULT_URLS, ToolRecorder, make_model, receipt_from_tool_result, run_strands_scenario

__all__ = ["DEFAULT_URLS", "ToolRecorder", "make_model", "receipt_from_tool_result", "run_strands_scenario"]
