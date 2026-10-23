"""CLI for deterministic trace replay and damage delta analysis."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence, TextIO

from agentguard.analytics import TraceValidationError, load_trace
from agentguard.analytics.damage import _calculate_validated_damage_delta
from agentguard.analytics.replay import _replay_validated_trace
from agentguard.analytics.scoreboard import scoreboard_report, write_scoreboard


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentguard", description="Replay and analyze a frozen AgentGuard Execution Trace JSON file.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("replay", "Replay the recorded tool-call and policy-decision sequence."),
        ("analyze", "Calculate the trace's protected/unprotected loss delta."),
        ("run", "Replay the trace and calculate its loss delta."),
    ):
        sub = subparsers.add_parser(command, help=help_text, description=help_text)
        sub.add_argument("trace", type=Path, help="Path to one Execution Trace JSON file (or a trace directory for aggregate analyze)")
        sub.add_argument("--format", choices=("json", "text"), default="json", help="Output format (default: json)")
        sub.add_argument("--output", type=Path, help="Write the report to this path instead of stdout")
    scoreboard = subparsers.add_parser("scoreboard", help="Build the eight-scenario HTML damage scoreboard from exported traces.")
    scoreboard.add_argument("runs", type=Path, nargs="?", default=Path("runs"), help="Directory containing exported scenario traces (default: runs/)")
    scoreboard.add_argument("--output", type=Path, default=Path("reports/damage-scoreboard.html"), help="HTML output path")
    return parser


def _report(command: str, trace_path: Path) -> dict:
    if command == "analyze" and trace_path.is_dir():
        scoreboard = scoreboard_report(trace_path)
        return {
            "command": command,
            "analytics": {
                "valid_scenarios": sum(row["status"] == "valid" for row in scoreboard["rows"]),
                "complete": scoreboard["complete"],
                "scenarios": scoreboard["rows"],
                "extras": scoreboard["extras"],
                "totals": scoreboard["totals"],
                "formula": "sum(unprotected_loss) - sum(protected_loss)",
            },
        }
    trace = load_trace(trace_path)
    if command == "replay":
        result = {"replay": _replay_validated_trace(trace)}
    elif command == "analyze":
        result = {"analytics": _calculate_validated_damage_delta(trace)}
    else:
        result = {
            "replay": _replay_validated_trace(trace),
            "analytics": _calculate_validated_damage_delta(trace),
        }
    return {"command": command, **result}


def _text_report(report: dict) -> str:
    analytics = report.get("analytics")
    if analytics is not None and "totals" in analytics:
        totals = analytics["totals"]
        lines = [f"AgentGuard analyze: {analytics['valid_scenarios']}/8 valid scenarios"]
        lines.append(f"Total naive loss: {totals['naive_loss']}")
        lines.append(f"Total guarded loss: {totals['guarded_loss']}")
        lines.append(f"Total damage delta: {totals['damage_prevented']}")
        lines.extend(f"  {row['scenario_id']}: {row['status']}" for row in analytics["scenarios"])
        return "\n".join(lines) + "\n"
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
    if args.command == "scoreboard":
        try:
            output_path, result = write_scoreboard(args.runs, args.output)
            valid_count = sum(row["status"] == "valid" for row in result["rows"])
            out.write(
                f"AgentGuard scoreboard: {valid_count}/8 valid scenarios; "
                f"naive=${result['totals']['naive_loss']:.2f}, "
                f"guarded=${result['totals']['guarded_loss']:.2f}, "
                f"damage delta=${result['totals']['damage_prevented']:.2f}\n"
                f"HTML: {output_path}\n"
            )
            if not result["complete"]:
                err.write("agentguard: scoreboard contains missing, invalid, duplicate, or unexpected traces; see highlighted rows.\n")
                return 1
            return 0
        except OSError as exc:
            err.write(f"agentguard: {exc}\n")
            return 1
    try:
        report = _report(args.command, args.trace)
        output = json.dumps(report, indent=2, ensure_ascii=False) + "\n" if args.format == "json" else _text_report(report)
        if args.output is not None:
            args.output.write_text(output, encoding="utf-8")
        else:
            out.write(output)
        if args.command == "analyze" and args.trace.is_dir() and not report["analytics"]["complete"]:
            err.write("agentguard: aggregate contains missing, invalid, duplicate, or unexpected traces.\n")
            return 1
        return 0
    except (TraceValidationError, OSError) as exc:
        err.write(f"agentguard: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
