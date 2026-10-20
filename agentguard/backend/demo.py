"""Smoke demo: exercises all five policies in one run."""
from __future__ import annotations

import json

from .seed import build_store
from .tools import BillingTools

CALLS: list[tuple[str, dict]] = [
    ("get_subscription", {"customer_id": "CUST-001"}),
    ("apply_discount", {"sub_id": "SUB-001", "percent": 20, "actor_id": "CUST-001"}),
    ("apply_discount", {"sub_id": "SUB-001", "percent": 15, "actor_id": "CUST-001"}),
    ("apply_discount", {"sub_id": "SUB-002", "percent": 50, "actor_id": "CUST-002"}),
    ("cancel_subscription", {"sub_id": "SUB-004", "actor_id": "CUST-001"}),
    ("issue_refund", {"sub_id": "SUB-001", "amount": 75, "actor_id": "CUST-001"}),
    ("issue_refund", {"sub_id": "SUB-001", "amount": 50, "actor_id": "CUST-001"}),
    ("issue_refund", {"sub_id": "SUB-002", "amount": 30, "actor_id": "CUST-002"}),
    ("cancel_subscription", {"sub_id": "SUB-001", "actor_id": "CUST-001"}),
    ("cancel_subscription", {"sub_id": "SUB-001", "actor_id": "CUST-001"}),
]


def main() -> None:
    store = build_store()
    tools = BillingTools(store)
    for name, kwargs in CALLS:
        result = tools.execute(name, **kwargs)
        codes = ", ".join(v.code for v in result.violations) or result.error_code or "-"
        print(f"{name:20} ok={str(result.ok):5} action={result.action:22} {codes}")
    print(f"refunds recorded: {len(store.refunds)} | events logged: {len(store.events)}")


if __name__ == "__main__":
    main()
