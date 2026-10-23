# Trace export, replay, analysis, and scoreboard

## Frozen trace contract

The strict loader uses the unversioned shape in `contracts.md`: `scenario_id`, `prompt`, `tool_calls`, `unprotected_loss`, and `protected_loss`. Each call has `tool`, `args`, and `policy_result` with `ALLOWED` or `BLOCKED` plus a nullable `violated_policy`. Missing/unknown fields, duplicate JSON keys, malformed input, invalid statuses, non-finite values, and negative input losses are rejected. No schema version or missing value is inferred.

## Export paired simulator runs

`export_trace(scenario, naive_run, guarded_run)` requires matching scenario IDs and the expected naive/guarded modes, with each run completed or a refusal. It joins customer messages with two newline characters and reads guarded tool calls from their full Contract v2 receipt objects.

Loss is computed from each run's initial and final snapshots: newly issued refunds plus the value over 12 months of increases to an existing or newly applied discount. The exporter rejects malformed or incomplete state rather than supplying zero. It does not calculate hypothetical loss for a blocked call. `write_trace` validates before writing.

The frozen trace keeps only ALLOWED or BLOCKED. The exporter reads each guarded call's Contract v2 receipt: ALLOWED remains ALLOWED, while BLOCKED, NEEDS_APPROVAL, and ERROR map to BLOCKED with the receipt's policy or error code. The trace does not carry the full receipt or execution metadata.

## Replay and analyze

```sh
agentguard replay trace.json [--format json|text] [--output report.json]
agentguard analyze trace.json [--format json|text] [--output report.json]
agentguard analyze runs/ [--format json|text] [--output aggregate.json]
agentguard run trace.json [--format json|text] [--output report.json]
```

Replay is deterministic and side-effect free; it does not call tools or recompute policy decisions. Damage delta is `unprotected_loss - protected_loss`; positive, zero, and negative values are retained and labeled honestly.

## Eight-scenario scoreboard

```sh
agentguard scoreboard runs/ --output reports/damage-scoreboard.html
```

The page reads each exported `<scenario>.trace.json` together with its naive and guarded raw run files in the same directory. Loss comes from the validated trace; `unauthorized_actions` counts executed receipt calls whose subscription owner differs from the authenticated customer. Missing or invalid traces or receipts are shown and excluded, and an incomplete scoreboard returns exit code 1.

## GitHub Action

`.github/actions/agentguard-trace` accepts `trace`, `command` (`replay`, `analyze`, or `run`), and `python-version`. It writes a JSON report and exposes `report-path`. `.github/workflows/tests.yml` runs the offline test suite across Python 3.10–3.13, invokes the action on the `micro_refund_split_01.json` contract fixture, and checks the report path, command, and damage delta.
