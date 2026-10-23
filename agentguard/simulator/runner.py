"""Runs scenarios against the naive or guarded agent and collects artifacts."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .agent import SupportAgent
from .contracts import BillingBackend
from .llm import LLMClient
from .records import AgentMode, ScenarioRun
from .scenarios import SCENARIOS, Scenario
from .tools import ToolExecutor

# Builds a fresh backend for one run: loaded from ``scenario.seed``, acting as
# ``scenario.authenticated_customer_id``, enforcing policies only when mode is
# "guarded". Called once per run so runs never share state. Person A's
# ``make_backend`` (agentguard/integration/backend.py) has this signature.
BackendFactory = Callable[[Scenario, AgentMode], BillingBackend]


def run_scenario(
    scenario: Scenario,
    mode: AgentMode,
    backend_factory: BackendFactory,
    llm: LLMClient,
) -> ScenarioRun:
    if mode not in ("naive", "guarded"):
        raise ValueError(f"mode must be 'naive' or 'guarded', got {mode!r}")

    backend = backend_factory(scenario, mode)
    executor = ToolExecutor(backend)
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
    scenarios: Iterable[Scenario] = SCENARIOS,
    on_complete: Callable[[ScenarioRun], None] | None = None,
) -> list[ScenarioRun]:
    runs = []
    for scenario in scenarios:
        run = run_scenario(scenario, mode, backend_factory, llm)
        runs.append(run)
        if on_complete:
            on_complete(run)
    return runs
