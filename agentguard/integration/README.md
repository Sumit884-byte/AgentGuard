# Integration: `make_backend` (contract v2 phase 1)

```python
from agentguard.integration import make_backend

backend = make_backend(scenario, "guarded")   # or "naive"
receipt = backend.issue_refund("C-1002", 500, "QA goodwill")
```

One fresh billing store, policy engine and cumulative refund state per call to
`make_backend`, built from `scenario.seed` with the store clock fixed at
2026-10-22T12:00:00Z (`AGENTGUARD_NOW` overrides it). It is the default backend
for `python -m agentguard.simulator`, `web/server.py` and the Strands stub
servers.

## What each call does

1. **Argument checks (both modes).** Unknown customer, non-numeric or
   non-positive amount, discount outside (0, 100], already-cancelled
   subscription: ERROR receipt with `invalid_arguments:<CODE>`.
2. **Guarded only: every check, in this order**, all reported in `checks`:
   - `handler`: `own_subscription_only` (also on `get_subscription`)
   - `yaml`: every applicable rule in `policy/policies/stripe.yaml`
   - `backend`: `backend/policies.py` (refund cap and window, discount cap,
     one discount per customer)

   `violated_policy` is the first failure; the call does not run.
3. **Safe alternative**, contract section 4, first match wins: ownership →
   none; refund window → cancel; refund cap → refund of the last charge (never
   more than what is left under the $50 cumulative cap); discount cap with no
   discount yet → 20%; otherwise none.
4. **Execute** through `BillingTools` (policies on in guarded, off in naive).
   `money` records what the call gave away; it matches the section 6 loss from
   state (tested). Guarded mode updates the cumulative refund state only when a
   refund executes.

`NEEDS_APPROVAL` never appears: supervisor approval (A6) is not implemented.

## Changes in the backend for contract v2

All additive; the v1 seed and tests behave as before.

| File | Change |
|---|---|
| `backend/models.py` | `Subscription.last_charged_at`, `last_charge_amount` |
| `backend/policies.py` | refund window measured from the last charge (`charge_date`), falling back to `started_at` |
| `backend/tools.py` | `BillingTools(store, enforce_policies=True)`; last charge in the subscription view |
| `policy/engine.py` | `evaluate_all()` reports every rule with the values it read; `evaluate()` unchanged |
| `mcp/handler.py` | `days_since_charge` uses the same charge date |

## Still to do (Person A)

- Retire `backend/seed.py` and `scenarios/ids.yaml` in favour of
  `integration/seed.py` (kept for now so existing tests and demos still run).
- Move `mcp/server.py` to MCP 2.x on Streamable HTTP with token identity
  (A1 to A3). `strands_agent/stub_server.py` already serves `make_backend` that
  way and can be the starting point.
- Supervisor approval (A6), if not cut.
