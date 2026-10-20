# Tool contract v1 (frozen Day 1)

## Result shape (every tool, every call)
    ToolResult(
      ok: bool,
      tool: str,
      action: str,
      data: dict | None,
      violations: list[PolicyViolation],   # {code, policy, detail}
      error_code: str | None,
      message: str,
    )

## action enum
    read | discount_applied | subscription_cancelled
    refund_issued | rejected | error

## Semantics
    Policy failure      -> ok=False, action="rejected", violations populated
    Argument/missing    -> ok=False, action="error",   error_code set, violations=[]
    Rejected call       -> state NEVER mutated

## Signatures
    get_subscription(customer_id)                       -> read-only
    apply_discount(sub_id, percent, actor_id)
    cancel_subscription(sub_id, actor_id)
    issue_refund(sub_id, amount, actor_id)
    # actor_id = the customer the agent is acting FOR (ownership rule)

## Stable violation codes -> policy name
    DISCOUNT_CAP_EXCEEDED    max_discount_20pct
    REFUND_CAP_EXCEEDED      max_refund_50_usd
    NOT_SUBSCRIPTION_OWNER   own_subscription_only
    REFUND_WINDOW_EXPIRED    refund_window_30_days
    DISCOUNT_ALREADY_USED    one_discount_per_customer

## Check order (deterministic)
    ownership -> amount cap -> one-discount / window

## Assumptions (state these in the report)
    - 30-day window measured from subscription.started_at
    - $50 cap applied per refund
    - ownership enforced on apply_discount, cancel_subscription, issue_refund

## Evaluator hooks
    store.snapshot()  -> JSON: customers, subscriptions, refunds, events
    store.events      -> every tool_call (args, ok, violations) + every state_change
