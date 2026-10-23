# Simulator & Agent (Person B)

Runs the billing support agent against 8 scripted adversarial customers, in
two modes, and records everything the evaluator needs. Follows
`contracts-v2.md` sections 2 and 4.

- **naive**: the backend runs every call with policies off.
- **guarded**: the backend checks ownership and every policy first.

Both modes use the same prompt, model, tools, seed and clock, so the
policies are the only difference.

## What the backend provides (Person A)

`make_backend(scenario, mode)` (see `contracts.py`) returns an object with
`get_subscription`, `apply_discount`, `cancel_subscription`, `issue_refund`
and `snapshot`. Each tool method returns a decision receipt and never raises.
The simulator maps receipts to records like this:

| receipt `status` | `allowed` | `executed` | `policy_reason` | `error` |
|---|---|---|---|---|
| ALLOWED | true | true | null | null |
| BLOCKED / NEEDS_APPROVAL | false | false | `"<violated_policy>: <reason>"` | null |
| ERROR | true | false | null | `reason` |

When a call is blocked, the model is told
`"Blocked by billing policy: <reason> <safe_alternative.say>"`.

## How to run it (Person C)

```python
from agentguard.simulator import default_llm, run_suite

# Gemini if only GEMINI_API_KEY is set, Claude if ANTHROPIC_API_KEY is set.
# Force one with AGENTGUARD_PROVIDER=gemini|anthropic. Models:
# AGENTGUARD_GEMINI_MODEL (default gemini-3.8-flash), AGENTGUARD_MODEL (default claude-opus-5-5).
llm = default_llm()
naive = run_suite("naive", make_backend, llm)
guarded = run_suite("guarded", make_backend, llm)
```

Each `ScenarioRun` has `initial_state`, `final_state`, `transcript`,
`tool_calls` (each with `allowed`, `executed`, `result`, `error`,
`policy_reason` and the full `receipt`), `targeted_policies` and `status`. `run.to_dict()` gives JSON.

`status` is `completed`, `refusal`, `max_tool_iterations`, or `error: ...`.
Partial artifacts are kept on error.

## Tests

`pytest` runs offline with an in-memory backend and a scripted LLM
(`tests/fakes.py`). No API key needed.

`pytest -m live -s` runs scenario S1 against the real model in both modes.
It reads keys from the environment or from `.env` (see `.env.example`).
