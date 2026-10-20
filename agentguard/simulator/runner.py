"""Runs scenarios against the naive or guarded agent and collects artifacts."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .agent import SupportAgent
from .contracts import BillingBackend, PolicyEngine
from .llm import LLMClient
from .records import AgentMode, ScenarioRun
from .scenarios import SCENARIOS, Scenario
from .tools import ToolExecutor

# Builds a fresh backend loaded with ``scenario.seed``. Called once per run so
# naive and guarded runs never share state.
BackendFactory = Callable[[Scenario], BillingBackend]


def run_scenario(
    scenario: Scenario,
    mode: AgentMode,
    backend_factory: BackendFactory,
    llm: LLMClient,
    policy_engine: PolicyEngine | None = None,
) -> ScenarioRun:
    if mode == "guarded" and policy_engine is None:
        raise ValueError("guarded mode requires a policy_engine")

    backend = backend_factory(scenario)
    context = {
        "authenticated_customer_id": scenario.authenticated_customer_id,
        "scenario_id": scenario.id,
    }
    executor = ToolExecutor(backend, context, policy_engine if mode == "guarded" else None)
    agent = SupportAgent(llm=llm, executor=executor, customer_id=scenario.authenticated_customer_id)

    run = ScenarioRun(
        scenario_id=scenario.id,
        attack_type=scenario.attack_type,
        mode=mode,
        model=llm.model,
        authenticated_customer_id=scenario.authenticated_customer_id,
        targeted_policies=list(scenario.targeted_policies),
        initial_state=backend.snapshot(),
        final_state={},
    )

    try:
        for turn, message in enumerate(scenario.customer_messages, start=1):
            outcome = agent.respond(turn, message)
            if outcome.status != "completed":
                run.status = outcome.status
                break
    except Exception as exc:  # keep partial artifacts; one bad run shouldn't kill the suite
        run.status = f"error: {type(exc).__name__}: {exc}"

    run.transcript = agent.transcript
    run.tool_calls = executor.calls
    run.final_state = backend.snapshot()
    return run


def run_suite(
    mode: AgentMode,
    backend_factory: BackendFactory,
    llm: LLMClient,
    policy_engine: PolicyEngine | None = None,
    scenarios: Iterable[Scenario] = SCENARIOS,
    on_complete: Callable[[ScenarioRun], None] | None = None,
) -> list[ScenarioRun]:
    runs = []
    for scenario in scenarios:
        run = run_scenario(scenario, mode, backend_factory, llm, policy_engine)
        runs.append(run)
        if on_complete:
            on_complete(run)
    return runs
