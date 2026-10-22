# Trace replay and damage delta

The analytics package reads the frozen Execution Trace shape: `scenario_id`, `prompt`, `tool_calls`, `unprotected_loss`, and `protected_loss`. Each call has `tool`, `args`, and a `policy_result` with `status` (`ALLOWED` or `BLOCKED`) and `violated_policy` (a string or `null`). Required fields and JSON types are checked. Missing or unknown fields, duplicate object keys at any nesting level, malformed JSON, oversized integer tokens, excessive nesting, and invalid values produce a concise validation error; no defaults are filled in. A `BLOCKED` decision requires a non-empty `violated_policy`; an `ALLOWED` decision requires `null`. Losses must be finite, non-negative JSON numbers (booleans are rejected). Parser limits are reported as CLI input errors rather than tracebacks.

The supplied shape does not contain `schema_version`; the loader does not invent one. Any schema evolution should be agreed and versioned by the contract owners. Unknown fields are rejected so drift cannot pass silently.

The simulator's `ScenarioRun.to_dict()` is not currently an Execution Trace adapter: `scenario_id` is available, but its `tool_calls` use `tool_name`, `arguments`, `allowed`, and `policy_reason` instead of the frozen call fields; it has no top-level `prompt`, `unprotected_loss`, or `protected_loss`. Loss values are not present in the run record or derivable authoritatively from it. Integration therefore remains blocked until the contract owners identify an authoritative prompt source/mapping and loss producer, and approve mappings for policy status and violated policy.

Replay is deterministic and side-effect free. It returns the calls in source order with their recorded policy decisions. It does not execute tools or rerun policies because the trace carries neither backend state nor policy configuration.

The damage delta is defined as:

```text
damage_delta = unprotected_loss - protected_loss
```

A positive result means the trace reports a lower loss value for the protected case by that difference; a negative result means the protected value is higher; zero means they are equal. The CLI reports only this arithmetic comparison and does not infer currency, realized savings, or causality.

## CLI

After installing the package, use:

```sh
agentguard replay trace.json [--format json|text] [--output report.json]
agentguard analyze trace.json [--format json|text] [--output report.json]
agentguard run trace.json [--format json|text] [--output report.json]
```

Output is JSON by default. `replay` reports the ordered recorded calls and counts; `analyze` reports the two input losses, formula, signed delta, and interpretation; `run` returns both reports. Exit codes are `0` for success, `1` for file/JSON/schema/output errors (including parser limits and unrepresentable delta arithmetic), and `2` for invalid command-line usage. The composite action emits a GitHub Actions error annotation on failure and preserves the CLI exit code.

The composite GitHub Action at `.github/actions/agentguard-trace` accepts `trace`, `command` (`replay`, `analyze`, or `run`), and `python-version` inputs. It writes a JSON report and exposes its path as the `report-path` output. The workflow runs on pushes and pull requests, tests Python 3.10 through 3.13, then exercises the composite Action against the contract fixture.
