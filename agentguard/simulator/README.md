# Simulator & Agent (Member 2)

Runs the billing support agent against 8 scripted adversarial customers, in
two modes, and records everything the evaluator needs.

- **naive**: tool calls go straight to the backend.
- **guarded**: every tool call goes through the policy engine first; blocked
  calls are logged and returned to the agent as errors.

Both modes use the same prompt and model, so the guardrail is the only
difference between them.

## What the backend needs to provide (Member 1)

See `contracts.py`. Duck typing is enough; no inheritance needed.

```python
class BillingBackend:
    def get_subscription(self, customer_id) -> dict
    def apply_discount(self, customer_id, percent, reason) -> dict
    def cancel_subscription(self, customer_id, reason) -> dict
    def issue_refund(self, customer_id, amount, reason) -> dict
    def snapshot(self) -> dict          # deep copy of full DB state

class PolicyEngine:
    def check(self, tool_name, arguments, context, backend) -> decision
        # decision has .allowed: bool and .reason: str
        # context = {"authenticated_customer_id": ..., "scenario_id": ...}
```

Raise an exception for invalid input; the simulator records it and shows it
to the agent as a tool error.

Each scenario has a `seed` dict (customers that must exist). You supply a
`backend_factory(scenario) -> BillingBackend` that builds a fresh database
from it. It is called once per run.

## How to run it (Shubhi)

```python
from agentguard.simulator import AnthropicLLM, run_suite

llm = AnthropicLLM()  # model from AGENTGUARD_MODEL, default claude-opus-5-5
naive = run_suite("naive", backend_factory, llm)
guarded = run_suite("guarded", backend_factory, llm, policy_engine=engine)
```

Each `ScenarioRun` has `initial_state`, `final_state`, `transcript`,
`tool_calls` (each with `allowed`, `executed`, `result`, `error`,
`policy_reason`), `targeted_policies` and `status`. `run.to_dict()` gives JSON.

`status` is `completed`, `refusal`, `max_tool_iterations`, or `error: ...`.
Partial artifacts are kept on error.

## Tests

`pytest` runs offline with an in-memory backend and a scripted LLM
(`tests/fakes.py`). No API key needed.
