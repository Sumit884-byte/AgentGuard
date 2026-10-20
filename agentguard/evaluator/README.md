# Billing evaluator

The evaluator audits a run using the snapshots provided by the simulator:

```python
from agentguard.evaluator import calculate_exposure, evaluate_run

evaluation = evaluate_run(run.initial_state, run.final_state)
exposure = calculate_exposure(run.initial_state, run.final_state)
```

It rechecks successful billing mutations against the frozen policy contract,
compares those mutations with the append-only event log and final customer,
subscription, and refund state, and records rejected policy attempts as
evidence. Rejected calls do not count as executed violations.

The exposure estimate counts the full amounts of successfully issued refunds
that violated policy. Discount exposure is excluded because the frozen backend
snapshot does not contain plan prices or a discount duration. The figure is a
simulated estimate, not actual financial loss.

Run evaluator and backend tests with `pytest -q`.
