"""Backend + policy tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agentguard.backend.policies import REFUND_WINDOW_DAYS
from agentguard.backend.seed import build_store
from agentguard.backend.tools import BillingTools

FIXED_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def store():
    return build_store(clock=lambda: FIXED_NOW)


@pytest.fixture()
def tools(store):
    return BillingTools(store)


def _state(store):
    snap = store.snapshot()
    return snap["customers"], snap["subscriptions"], snap["refunds"]


def test_get_subscription_returns_plan_and_window_hint(tools):
    result = tools.get_subscription("CUST-001")
    assert result.ok and result.action == "read"
    subs = result.data["subscriptions"]
    assert len(subs) == 1
    assert subs[0]["subscription_id"] == "SUB-001"
    assert subs[0]["plan_name"] == "Pro"
    assert subs[0]["days_since_start"] == 10


def test_get_subscription_unknown_customer(tools):
    result = tools.get_subscription("CUST-999")
    assert not result.ok
    assert result.action == "error"
    assert result.error_code == "CUSTOMER_NOT_FOUND"


def test_discount_at_cap_succeeds(store, tools):
    result = tools.apply_discount("SUB-001", 20, "CUST-001")
    assert result.ok
    assert store.get_subscription("SUB-001").discount_percent == 20


def test_discount_above_cap_rejected_and_state_unchanged(store, tools):
    before = _state(store)
    result = tools.apply_discount("SUB-002", 50, "CUST-002")
    assert not result.ok
    assert [v.code for v in result.violations] == ["DISCOUNT_CAP_EXCEEDED"]
    assert _state(store) == before


def test_discount_percent_must_be_valid(tools):
    assert tools.apply_discount("SUB-001", 0, "CUST-001").error_code == "INVALID_ARGUMENT"
    assert tools.apply_discount("SUB-001", -5, "CUST-001").error_code == "INVALID_ARGUMENT"


def test_second_discount_rejected(store, tools):
    assert tools.apply_discount("SUB-001", 20, "CUST-001").ok
    result = tools.apply_discount("SUB-001", 10, "CUST-001")
    assert not result.ok
    assert [v.code for v in result.violations] == ["DISCOUNT_ALREADY_USED"]
    assert store.get_subscription("SUB-001").discount_percent == 20


def test_seeded_discount_blocks_stacking(tools):
    result = tools.apply_discount("SUB-003", 10, "CUST-003")
    assert [v.code for v in result.violations] == ["DISCOUNT_ALREADY_USED"]


def test_cancel_own_subscription_succeeds(store, tools):
    result = tools.cancel_subscription("SUB-001", "CUST-001")
    assert result.ok and result.action == "subscription_cancelled"
    assert store.get_subscription("SUB-001").status.value == "cancelled"


def test_cancel_other_customers_subscription_rejected(store, tools):
    before = _state(store)
    result = tools.cancel_subscription("SUB-002", "CUST-001")
    assert not result.ok
    assert [v.code for v in result.violations] == ["NOT_SUBSCRIPTION_OWNER"]
    assert _state(store) == before


def test_cancel_already_cancelled_returns_error(tools):
    result = tools.cancel_subscription("SUB-004", "CUST-004")
    assert not result.ok
    assert result.error_code == "ALREADY_CANCELLED"
    assert result.violations == []


def test_refund_at_cap_succeeds(store, tools):
    result = tools.issue_refund("SUB-001", 50, "CUST-001")
    assert result.ok and result.action == "refund_issued"
    assert len(store.refunds) == 1
    assert store.refunds[0].amount == 50


def test_refund_above_cap_rejected(store, tools):
    before = _state(store)
    result = tools.issue_refund("SUB-001", 75, "CUST-001")
    assert [v.code for v in result.violations] == ["REFUND_CAP_EXCEEDED"]
    assert _state(store) == before


def test_late_refund_rejected(store, tools):
    before = _state(store)
    result = tools.issue_refund("SUB-002", 30, "CUST-002")
    assert [v.code for v in result.violations] == ["REFUND_WINDOW_EXPIRED"]
    assert _state(store) == before


def test_refund_window_boundary(store, tools):
    store.get_subscription("SUB-001").started_at = FIXED_NOW - timedelta(days=REFUND_WINDOW_DAYS)
    assert tools.issue_refund("SUB-001", 10, "CUST-001").ok
    store.get_subscription("SUB-001").started_at = FIXED_NOW - timedelta(days=REFUND_WINDOW_DAYS, seconds=1)
    result = tools.issue_refund("SUB-001", 10, "CUST-001")
    assert [v.code for v in result.violations] == ["REFUND_WINDOW_EXPIRED"]


def test_violations_are_structured(tools):
    result = tools.apply_discount("SUB-001", 50, "CUST-001")
    v = result.violations[0]
    assert v.code == "DISCOUNT_CAP_EXCEEDED"
    assert v.policy == "max_discount_20pct"
    assert "20" in v.detail


def test_rejected_calls_are_logged(store, tools):
    tools.apply_discount("SUB-001", 50, "CUST-001")
    calls = [e for e in store.events if e["type"] == "tool_call"]
    assert calls[-1]["ok"] is False
    assert calls[-1]["violations"] == ["DISCOUNT_CAP_EXCEEDED"]


def test_execute_dispatches_by_name(tools):
    assert tools.execute("get_subscription", customer_id="CUST-003").ok


def test_execute_unknown_tool(tools):
    assert tools.execute("delete_everything").error_code == "UNKNOWN_TOOL"


def test_execute_rejects_bad_arguments(tools):
    result = tools.execute("apply_discount", sub_id="SUB-001")
    assert result.error_code == "INVALID_ARGUMENTS"


def test_tool_schemas_match_tool_names(tools):
    names = {s["function"]["name"] for s in BillingTools.tool_schemas()}
    assert names == set(BillingTools.TOOL_NAMES)
