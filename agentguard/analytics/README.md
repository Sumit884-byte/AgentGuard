# Trace replay and damage delta

The analytics package reads the frozen Execution Trace shape: `scenario_id`, `prompt`, `tool_calls`, `unprotected_loss`, and `protected_loss`. Each call has `tool`, `args`, and a `policy_result` with `status` (`ALLOWED` or `BLOCKED`) and `violated_policy` (a string or `null`). Required fields and JSON types are checked. Missing or unknown fields, malformed JSON, and invalid values produce a clear validation error; no defaults are filled in.

The supplied shape does not contain `schema_version`; the loader does not invent one. Any schema evolution should be agreed and versioned by the contract owners. Unknown fields are rejected so drift cannot pass silently.

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

Output is JSON by default. `replay` reports the ordered recorded calls and counts; `analyze` reports the two input losses, formula, signed delta, and interpretation; `run` returns both reports. Exit codes are `0` for success, `1` for file/JSON/schema/output errors, and `2` for invalid command-line usage.

The composite GitHub Action at `.github/actions/agentguard-trace` accepts `trace`, `command` (`replay`, `analyze`, or `run`), and `python-version` inputs. It writes a JSON report and exposes its path as the `report-path` output. The workflow runs on pushes and pull requests, tests Python 3.10 through 3.13, then exercises the composite Action against the contract fixture.
