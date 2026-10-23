"""Run scenarios with the Strands agent against the billing MCP servers and save them.

    python -m agentguard.strands_agent                          # Bedrock, S1..S8, both servers
    python -m agentguard.strands_agent --provider gemini --scenarios S1
    python -m agentguard.strands_agent --guarded-url http://host:8002/mcp --modes guarded
    python -m agentguard.strands_agent --skill skills/agentguard-billing

Start the servers first (Person A's, or the stub in stub_server.py). Writes
runs/<run_id>/<scenario>.<mode>.json in the same format as the in-process runs.
"""

from __future__ import annotations

import argparse
import sys

from ..simulator.__main__ import _load_dotenv
from ..simulator.scenarios import SCENARIOS, get_scenario
from ..simulator.storage import DEFAULT_RUNS_DIR, new_run_dir, save_run
from .agent import DEFAULT_URLS, make_model, run_strands_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agentguard.strands_agent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["bedrock", "gemini"], default="bedrock")
    parser.add_argument("--scenarios", nargs="+", default=[s.id for s in SCENARIOS])
    parser.add_argument("--modes", nargs="+", choices=["naive", "guarded"], default=["naive", "guarded"])
    parser.add_argument("--naive-url", default=DEFAULT_URLS["naive"])
    parser.add_argument("--guarded-url", default=DEFAULT_URLS["guarded"])
    parser.add_argument("--skill", action="append", help="Agent Skill directory to load (repeatable)")
    parser.add_argument("--out", default=str(DEFAULT_RUNS_DIR))
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)

    _load_dotenv()
    model = make_model(args.provider)
    urls = {"naive": args.naive_url, "guarded": args.guarded_url}
    run_dir = new_run_dir(args.out, args.run_id)
    print(f"Saving to {run_dir} (Strands, provider {args.provider})")

    failures = 0
    for scenario in (get_scenario(s) for s in args.scenarios):
        for mode in args.modes:
            run = run_strands_scenario(scenario, mode, model, urls[mode], skills=args.skill)
            save_run(run, run_dir)
            print(f"  {scenario.id} {mode:<7} {run.status:<12} calls={len(run.tool_calls)} "
                  f"blocked={len(run.blocked_calls)}")
            failures += run.status != "completed"
    print(f"Done: {len(args.scenarios) * len(args.modes)} runs, {failures} not completed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
