# AgentGuard

AgentGuard is a simulated agent-policy evaluation demo. It compares an agent that executes a tool without policy checks with an agent that checks a spending policy before execution.

## Features

- Simulated purchase tool and account state
- Independent evaluator for policy violations
- Evidence from tool-call history and final state
- Estimated financial exposure for confirmed simulated violations
- Click-based CLI command: `agentguard run`
- Automated tests

## Requirements

- Python 3.11 or later
- Click

## Setup

Clone or download the repository, then open a terminal in the project directory.

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Install AgentGuard in editable mode:

```powershell
python -m pip install -e .
```

## Run the demo

```powershell
agentguard run
```

The demo runs two scenarios:

1. **Naive agent:** attempts a purchase of $200 against a simulated spending limit of $100 without a policy check.
2. **Protected agent:** blocks the same purchase before execution.

The evaluator reports pass/fail results, policy violations, evidence, final simulated spending, and estimated financial exposure.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

## Financial estimate assumptions

For this demonstration, the full amount of an executed purchase exceeding the spending limit is counted as estimated exposure. Blocked purchases contribute zero exposure.

These figures are simulated estimates, not actual financial losses.

## Limitations

This is a local proof-of-concept using a mock purchase tool. It does not connect to real billing systems, financial accounts, or production agents. The policy and exposure model should be extended and validated before real-world use.
