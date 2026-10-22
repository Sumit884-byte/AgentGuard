"""Command-line spending-policy evaluation demo."""
from __future__ import annotations

import argparse

from agentguard.evaluator.financial import calculate_exposure
from agentguard.evaluator.spending import evaluate_run
from agentguard.simulator.spending_demo import Simulator


def run_scenario(protected: bool):
    simulator = Simulator(spending_limit=100)
    event = simulator.purchase(amount=200, protected=protected)
    state = simulator.get_state()
    evaluation = evaluate_run(simulator.tool_history, state)
    financial = calculate_exposure(simulator.tool_history, state["spending_limit"])
    return event, state, evaluation, financial


def print_report(name: str, protected: bool) -> bool:
    event, state, evaluation, financial = run_scenario(protected)
    print(f"\n{'=' * 45}\n{name}\n{'=' * 45}")
    print(f"Attempted action: {event['tool']}")
    print(f"Requested amount: ${event['amount']:.2f}")
    print(f"Policy enforcement: {'ENABLED' if protected else 'DISABLED'}")
    print(f"Tool execution: {'EXECUTED' if event['executed'] else 'BLOCKED'}")
    print(f"Evaluation: {'PASS' if evaluation['passed'] else 'FAIL'}")
    print("Policy violations:")
    for violation in evaluation["violations"] or ["None"]:
        print(f"  - {violation}")
    print("Evidence:")
    for item in evaluation["evidence"] or ["No issues detected."]:
        print(f"  - {item}")
    print(f"Final simulated spending: ${state['balance_spent']:.2f}")
    print(f"Estimated financial exposure: ${financial['estimated_exposure']:.2f}")
    print(f"Exposure assumption: {financial['assumption']}")
    return evaluation["passed"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare naive and spending-policy-protected purchase simulations.")
    parser.parse_args()
    print("AGENTGUARD SPENDING POLICY DEMO")
    print_report("NAIVE AGENT", protected=False)
    print_report("PROTECTED AGENT", protected=True)


if __name__ == "__main__":
    main()
