"""Save and load runs in the contracts-v2 section 6 layout.

    runs/<run_id>/S1.naive.json     raw ScenarioRun.to_dict()
    runs/<run_id>/S1.guarded.json
    runs/<run_id>/S1.trace.json     written by the exporter (Person C), not here
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .records import ScenarioRun, ToolCallRecord, TranscriptEntry

DEFAULT_RUNS_DIR = Path("runs")


def new_run_dir(root: Path | str = DEFAULT_RUNS_DIR, run_id: str | None = None) -> Path:
    """Create and return ``<root>/<run_id>``; run_id defaults to a UTC timestamp."""
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path(root) / run_id
    path.mkdir(parents=True, exist_ok=False)
    return path


def run_filename(scenario_id: str, mode: str) -> str:
    return f"{scenario_id}.{mode}.json"


def save_run(run: ScenarioRun, run_dir: Path | str) -> Path:
    path = Path(run_dir) / run_filename(run.scenario_id, run.mode)
    path.write_text(json.dumps(run.to_dict(), indent=2, default=str) + "\n")
    return path


def run_from_dict(data: dict[str, Any]) -> ScenarioRun:
    data = dict(data)
    transcript = [TranscriptEntry(**e) for e in data.pop("transcript", [])]
    tool_calls = [ToolCallRecord(**c) for c in data.pop("tool_calls", [])]
    return ScenarioRun(**data, transcript=transcript, tool_calls=tool_calls)


def load_run(path: Path | str) -> ScenarioRun:
    return run_from_dict(json.loads(Path(path).read_text()))


def load_run_dir(run_dir: Path | str) -> dict[tuple[str, str], ScenarioRun]:
    """Load every ``<scenario>.<mode>.json`` in a run directory, keyed by (scenario_id, mode)."""
    runs = {}
    for path in sorted(Path(run_dir).glob("*.json")):
        parts = path.name.split(".")
        if len(parts) == 3 and parts[1] in ("naive", "guarded"):
            run = load_run(path)
            runs[(run.scenario_id, run.mode)] = run
    return runs
