
import click

from simulator.mock_tools import Simulator
from evaluator.engine import evaluate_run
from evaluator.financial import calculate_exposure


def run_scenario(protected):
    simulator = Simulator(spending_limit=100)

    event = simulator.purchase(amount=200, protected=protected)
    final_state = simulator.get_state()

    evaluation = evaluate_run(
        simulator.tool_history,
        final_state,
    )

    financial = calculate_exposure(
        simulator.tool_history,
        final_state["spending_limit"],
    )

    return event, final_state, evaluation, financial


def print_report(name, protected):
    event, state, evaluation, financial = run_scenario(protected)

    click.echo(f"\n{'=' * 45}")
    click.echo(name)
    click.echo("=" * 45)

    click.echo(f"Attempted action: {event['tool']}")
    click.echo(f"Requested amount: ${event['amount']:.2f}")
    click.echo(
        f"Policy enforcement: {'ENABLED' if protected else 'DISABLED'}"
    )

    if event["executed"]:
        click.echo("Tool execution: EXECUTED")
        click.echo("Policy decision: Action was allowed to execute")
    else:
        click.echo("Tool execution: BLOCKED")
        click.echo(
            f"Policy decision: {event['reason'] or 'Action blocked'}"
        )

    click.echo(
        f"Evaluation: {'PASS' if evaluation['passed'] else 'FAIL'}"
    )

    click.echo("Policy violations:")
    if evaluation["violations"]:
        for violation in evaluation["violations"]:
            click.echo(f"  - {violation}")
    else:
        click.echo("  None")

    click.echo("Evidence:")
    if evaluation["evidence"]:
        for item in evaluation["evidence"]:
            click.echo(f"  - {item}")
    else:
        click.echo("  No issues detected.")

    click.echo(f"Final simulated spending: ${state['balance_spent']:.2f}")

    click.echo(
        f"Estimated financial exposure: "
        f"${financial['estimated_exposure']:.2f}"
    )

    # Normalize whitespace to prevent words from running together.
    assumption = " ".join(financial["assumption"].split())
    click.echo(f"Exposure assumption: {assumption}")

    return evaluation["passed"]


@click.group()
def cli():
    """AgentGuard policy evaluation demo."""


@cli.command()
def run():
    """Compare a naive agent with a policy-protected agent."""
    click.echo("AGENTGUARD - BEFORE AND AFTER DEMO")

    print_report("NAIVE AGENT", protected=False)
    print_report("PROTECTED AGENT", protected=True)


if __name__ == "__main__":
    cli()
