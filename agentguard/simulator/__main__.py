"""Run scenarios in both modes and save them (B4).

    python -m agentguard.simulator                       # all 8 scenarios, naive + guarded
    python -m agentguard.simulator --scenarios S1 S3 --modes guarded
    python -m agentguard.simulator --backend tests.fakes:backend_factory   # dev only

Writes runs/<run_id>/<scenario>.<mode>.json. The model comes from default_llm()
(AGENTGUARD_PROVIDER and the keys in .env).
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

from .llm import default_llm
from .runner import run_scenario
from .scenarios import SCENARIOS, get_scenario
from .storage import DEFAULT_RUNS_DIR, new_run_dir, save_run


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip().strip("'\"")
            if value:
                os.environ.setdefault(key.strip(), value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agentguard.simulator", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", default="agentguard.integration.backend:make_backend",
                        help="module:function returning a backend for (scenario, mode)")
    parser.add_argument("--scenarios", nargs="+", default=[s.id for s in SCENARIOS])
    parser.add_argument("--modes", nargs="+", choices=["naive", "guarded"], default=["naive", "guarded"])
    parser.add_argument("--out", default=str(DEFAULT_RUNS_DIR), help="root folder for run directories")
    parser.add_argument("--run-id", help="run directory name (default: UTC timestamp)")
    args = parser.parse_args(argv)

    _load_dotenv()
    sys.path.insert(0, os.getcwd())
    module_name, _, attr = args.backend.partition(":")
    try:
        factory = getattr(importlib.import_module(module_name), attr)
    except (ImportError, AttributeError) as exc:
        parser.error(f"cannot load backend {args.backend!r}: {exc}")

    scenarios = [get_scenario(s) for s in args.scenarios]
    llm = default_llm()
    run_dir = new_run_dir(args.out, args.run_id)
    print(f"Saving to {run_dir} (model {llm.model}, backend {args.backend})")

    failures = 0
    for scenario in scenarios:
        for mode in args.modes:
            run = run_scenario(scenario, mode, factory, llm)
            path = save_run(run, run_dir)
            blocked = len(run.blocked_calls)
            print(f"  {scenario.id} {mode:<7} {run.status:<12} calls={len(run.tool_calls)} blocked={blocked}  {path.name}")
            failures += run.status != "completed"

    print(f"Done: {len(scenarios) * len(args.modes)} runs, {failures} not completed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
