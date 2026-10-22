# Spending policy demo

This demo compares an unguarded purchase tool with one that checks a spending limit before execution. It runs entirely in memory and is separate from the billing support simulator.

Install the repository with its development dependencies, then run:

```sh
agentguard-spending-demo
```

The independent evaluator checks tool history against final state and policy limits. The exposure estimate counts the full amount of each executed over-limit purchase; it is a simulated estimate, not actual financial loss.
