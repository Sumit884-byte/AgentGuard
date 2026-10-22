"""CLI for deterministic trace replay and damage delta analysis."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence, TextIO

from agentguard.analytics import TraceValidationError, calculate_damage_delta, load_trace, replay_trace


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentguard", description="Replay and analyze a frozen AgentGuard Execution Trace JSON file.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("replay", "Replay the recorded tool-call and policy-decision sequence."),
        ("analyze", "Calculate the trace's protected/unprotected loss delta."),
        ("run", "Replay the trace and calculate its loss delta."),
    ):
        sub = subparsers.add_parser(command, help=help_text, description=help_text)
        sub.add_argument("trace", type=Path, help="Path to one Execution Trace JSON file")
        sub.add_argument("--format", choices=("json", "text"), default="json", help="Output format (default: json)")
        sub.add_argument("--output", type=Path, help="Write the report to this path instead of stdout")
    return parser


def _report(command: str, trace_path: Path) -> dict:
    trace = load_trace(trace_path)
    if command == "replay":
        result = {"replay": replay_trace(trace)}
    elif command == "analyze":
        result = {"analytics": calculate_damage_delta(trace)}
    else:
        result = {"replay": replay_trace(trace), "analytics": calculate_damage_delta(trace)}
    return {"command": command, **result}


def _text_report(report: dict) -> str:
    lines = [f"AgentGuard {report['command']}: scenario {report.get('replay', report.get('analytics'))['scenario_id']}"]
    replay = report.get("replay")
    if replay is not None:
        summary = replay["summary"]
        lines.append(f"Replay: {summary['total']} calls ({summary['allowed']} allowed, {summary['blocked']} blocked)")
        for call in replay["replayed_calls"]:
            decision = call["policy_result"]
            suffix = f"; policy={decision['violated_policy']}" if decision["violated_policy"] is not None else ""
            lines.append(f"  {call['sequence']}. {call['tool']}: {decision['status']}{suffix}")
    analytics = report.get("analytics")
    if analytics is not None:
        lines.append(f"Damage delta (unprotected_loss - protected_loss): {analytics['damage_delta']}")
        lines.append(f"Interpretation: {analytics['interpretation']}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None, *, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    """Run the CLI. Returns 0 on success, 1 on file/schema errors; argparse uses 2 for usage errors."""
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    args = _parser().parse_args(argv)
    try:
        report = _report(args.command, args.trace)
        output = json.dumps(report, indent=2, ensure_ascii=False) + "\n" if args.format == "json" else _text_report(report)
        if args.output is not None:
            args.output.write_text(output, encoding="utf-8")
        else:
            out.write(output)
        return 0
    except (TraceValidationError, OSError) as exc:
        err.write(f"agentguard: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
