"""Tests for the MCP handler — policy enforcement without a real client."""
import pytest

from agentguard.mcp.handler import BillingHandler, ToolBlocked


@pytest.fixture()
def handler():
    return BillingHandler()


def test_allowed_refund_returns_payload(handler):
    out = handler.handle(
        "issue_refund",
        {
            "charge_id": "ch_A",
            "amount": 25.00,
            "reason": "customer complaint",
            "days_since_charge": 5,
        },
        "sess_1",
    )
    assert out["status"] == "ALLOWED"
    assert out["tool"] == "issue_refund"
    assert out["session_id"] == "sess_1"


def test_blocked_single_cap_raises_tool_blocked(handler):
    with pytest.raises(ToolBlocked) as exc_info:
        handler.handle(
            "issue_refund",
            {
                "charge_id": "ch_A",
                "amount": 75.00,
                "reason": "customer complaint",
                "days_since_charge": 5,
            },
            "sess_1",
        )
    assert exc_info.value.violated_policy == "max_single_refund"


def test_split_refund_blocked_at_handler_level(handler):
    """Same exploit as engine test, but through the MCP handler."""
    handler.handle(
        "issue_refund",
        {
            "charge_id": "ch_123",
            "amount": 30.00,
            "reason": "customer complaint",
            "days_since_charge": 5,
        },
        "sess_split",
    )
    with pytest.raises(ToolBlocked) as exc_info:
        handler.handle(
            "issue_refund",
            {
                "charge_id": "ch_123",
                "amount": 30.00,
                "reason": "customer complaint",
                "days_since_charge": 5,
            },
            "sess_split",
        )
    assert exc_info.value.violated_policy == "max_daily_refund_cap"


def test_sessions_are_isolated(handler):
    handler.handle(
        "issue_refund",
        {
            "charge_id": "ch_A",
            "amount": 40.00,
            "reason": "customer complaint",
            "days_since_charge": 5,
        },
        "sess_1",
    )
    # Same charge, different session — should not see sess_1's total.
    out = handler.handle(
        "issue_refund",
        {
            "charge_id": "ch_A",
            "amount": 40.00,
            "reason": "customer complaint",
            "days_since_charge": 5,
        },
        "sess_2",
    )
    assert out["status"] == "ALLOWED"


def test_refund_requires_reason(handler):
    with pytest.raises(ToolBlocked) as exc_info:
        handler.handle(
            "issue_refund",
            {
                "charge_id": "ch_A",
                "amount": 10.00,
                "reason": "",
                "days_since_charge": 5,
            },
            "sess_1",
        )
    assert exc_info.value.violated_policy == "refund_requires_reason"


def test_refund_after_30_days_blocked(handler):
    with pytest.raises(ToolBlocked) as exc_info:
        handler.handle(
            "issue_refund",
            {
                "charge_id": "ch_A",
                "amount": 10.00,
                "reason": "customer complaint",
                "days_since_charge": 45,
            },
            "sess_1",
        )
    assert exc_info.value.violated_policy == "no_refund_after_30_days"
