"""Tests for the MCP handler — real BillingTools wiring + exploit regression.

Each test proves one of the four findings from the PR review:
  1. BillingTools is actually called (returns real ToolResult, mutates state)
  2. Negative amounts are blocked (policy + BillingTools defense-in-depth)
  3. Misreported days_since_charge is ignored (handler uses store data)
  4. Session ID changes do not reset cumulative state
  5. Actor cannot refund another customer's subscription
"""
import pytest

from agentguard.mcp.handler import BillingHandler, ToolBlocked


@pytest.fixture()
def handler():
    return BillingHandler()


def _refund(sub_id, amount, actor_id="CUST-001", reason="customer complaint"):
    return {
        "charge_id": sub_id,
        "amount": amount,
        "actor_id": actor_id,
        "reason": reason,
    }


# --- 1. BillingTools is actually wired ------------------------------

def test_allowed_refund_mutates_billing_state(handler):
    """The handler must call BillingTools — return its ToolResult + mutate store."""
    out = handler.handle("issue_refund", _refund("SUB-001", 25.0), "s1")
    assert out["ok"] is True
    assert out["action"] == "refund_issued"
    assert out["data"]["amount"] == 25.0
    # Proof: real mutation happened in BillingTools' store, not a stub return.
    assert len(handler.billing.store.refunds) == 1
    assert handler.billing.store.refunds[0].amount == 25.0


# --- 2. Split-refund exploit (per-call passes, cumulative blocks) ----

def test_split_refund_blocked_at_cumulative_cap(handler):
    handler.handle("issue_refund", _refund("SUB-001", 30.0), "s1")
    with pytest.raises(ToolBlocked) as exc:
        handler.handle("issue_refund", _refund("SUB-001", 30.0), "s1")
    assert exc.value.violated_policy == "max_daily_refund_cap"
    # Only the first $30 was actually refunded.
    assert len(handler.billing.store.refunds) == 1


# --- 3. Session spoofing cannot reset cumulative state --------------

def test_session_change_does_not_reset_cumulative(handler):
    handler.handle("issue_refund", _refund("SUB-001", 30.0), "sess_A")
    # Same sub, different session — the cap must still hold.
    with pytest.raises(ToolBlocked) as exc:
        handler.handle("issue_refund", _refund("SUB-001", 30.0), "sess_B")
    assert exc.value.violated_policy == "max_daily_refund_cap"


# --- 4. Negative amounts are blocked --------------------------------

def test_negative_amount_blocked(handler):
    with pytest.raises(ToolBlocked) as exc:
        handler.handle("issue_refund", _refund("SUB-001", -1000.0), "s1")
    assert exc.value.violated_policy == "max_single_refund"
    assert len(handler.billing.store.refunds) == 0


# --- 5. Misreported days_since_charge is ignored --------------------

def test_misreported_days_since_charge_ignored(handler):
    """SUB-002 is 90 days old in seed. Client claims 5. Handler must use 90."""
    args = _refund("SUB-002", 10.0, actor_id="CUST-002")
    args["days_since_charge"] = 5  # lie
    with pytest.raises(ToolBlocked) as exc:
        handler.handle("issue_refund", args, "s1")
    assert exc.value.violated_policy == "no_refund_after_30_days"
    assert len(handler.billing.store.refunds) == 0


# --- 6. Actor cannot refund someone else's sub ----------------------

def test_actor_cannot_refund_other_customers_sub(handler):
    """SUB-003 belongs to CUST-003. CUST-001 must not refund it."""
    with pytest.raises(ToolBlocked) as exc:
        handler.handle("issue_refund", _refund("SUB-003", 10.0, actor_id="CUST-001"), "s1")
    assert exc.value.violated_policy == "own_subscription_only"


# --- 7. Reason required (YAML policy) -------------------------------

def test_refund_requires_reason(handler):
    with pytest.raises(ToolBlocked) as exc:
        handler.handle("issue_refund", _refund("SUB-001", 10.0, reason=""), "s1")
    assert exc.value.violated_policy == "refund_requires_reason"


# --- 8. After 30 days blocked (authoritative window check) ----------

def test_refund_after_window_blocked(handler):
    """SUB-002 is 90 days old — no client lie, straight through to window check."""
    with pytest.raises(ToolBlocked) as exc:
        handler.handle("issue_refund", _refund("SUB-002", 10.0, actor_id="CUST-002"), "s1")
    assert exc.value.violated_policy == "no_refund_after_30_days"


# --- 9. apply_discount works via subscription_id normalization -----

def test_apply_discount_via_subscription_id(handler):
    """MCP tool sends subscription_id; handler must normalize to sub_id."""
    out = handler.handle(
        "apply_discount",
        {"subscription_id": "SUB-001", "percent": 15.0, "actor_id": "CUST-001"},
        "s1",
    )
    assert out["ok"] is True
    assert out["action"] == "discount_applied"
    assert handler.billing.store.get_subscription("SUB-001").discount_percent == 15.0


def test_apply_discount_over_cap_blocked(handler):
    with pytest.raises(ToolBlocked) as exc:
        handler.handle(
            "apply_discount",
            {"subscription_id": "SUB-001", "percent": 50.0, "actor_id": "CUST-001"},
            "s1",
        )
    assert exc.value.violated_policy == "max_discount_20pct"


# --- 10. cancel_subscription works via subscription_id normalization

def test_cancel_via_subscription_id(handler):
    out = handler.handle(
        "cancel_subscription",
        {"subscription_id": "SUB-001", "actor_id": "CUST-001"},
        "s1",
    )
    assert out["ok"] is True
    assert out["action"] == "subscription_cancelled"
    assert handler.billing.store.get_subscription("SUB-001").status.value == "cancelled"


def test_cancel_other_customers_sub_blocked(handler):
    with pytest.raises(ToolBlocked) as exc:
        handler.handle(
            "cancel_subscription",
            {"subscription_id": "SUB-002", "actor_id": "CUST-001"},
            "s1",
        )
    assert exc.value.violated_policy == "own_subscription_only"
