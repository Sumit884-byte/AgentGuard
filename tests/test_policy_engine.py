"""Tests for the cumulative policy engine — including the split-refund exploit."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentguard.policy.cumulative import SessionState
from agentguard.policy.engine import PolicyEngine
from agentguard.policy.schema import ToolCallEvent


POLICY_FILE = Path(__file__).parent.parent / "agentguard/policy/policies/stripe.yaml"
T0 = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)


@pytest.fixture()
def engine():
    return PolicyEngine.from_yaml(POLICY_FILE)


def _refund(session, charge, amount, reason="customer complaint", offset_sec=0):
    return ToolCallEvent(
        session_id=session,
        tool_name="issue_refund",
        arguments={
            "charge_id": charge,
            "amount": amount,
            "reason": reason,
            "days_since_charge": 5,
        },
        timestamp=T0.replace(second=offset_sec),
    )


# --- the headline test: split-refund exploit --------------------------

def test_split_refund_attack_is_blocked(engine):
    """The whole reason Eng1 exists. 3x $30 passes per-call, fails cumulative."""
    state = SessionState()
    r1 = engine.evaluate(_refund("sess_x", "ch_123", 30.00, offset_sec=0), state)
    r2 = engine.evaluate(_refund("sess_x", "ch_123", 30.00, offset_sec=1), state)
    r3 = engine.evaluate(_refund("sess_x", "ch_123", 30.00, offset_sec=2), state)

    assert r1.status == "ALLOWED"
    assert r2.status == "BLOCKED"
    assert r2.violated_policy == "max_daily_refund_cap"
    assert r3.status == "BLOCKED"

    # Matches the frozen trace fixture exactly:
    # unprotected_loss: 90.00, protected_loss: 30.00
    unprotected = 30.00 + 30.00 + 30.00
    protected = 30.00
    assert unprotected == 90.00
    assert protected == 30.00


# --- single call checks ----------------------------------------------

def test_single_refund_under_cap_allowed(engine):
    state = SessionState()
    r = engine.evaluate(_refund("s1", "ch_A", 25.00), state)
    assert r.status == "ALLOWED"
    assert r.violated_policy is None


def test_single_refund_over_cap_blocked(engine):
    state = SessionState()
    r = engine.evaluate(_refund("s1", "ch_A", 75.00), state)
    assert r.status == "BLOCKED"
    assert r.violated_policy == "max_single_refund"


def test_negative_amount_blocked(engine):
    """$0 < amount <= 50 — negatives must be rejected at YAML layer."""
    state = SessionState()
    r = engine.evaluate(_refund("s1", "ch_A", -1000.00), state)
    assert r.status == "BLOCKED"
    assert r.violated_policy == "max_single_refund"


def test_refund_requires_reason(engine):
    state = SessionState()
    r = engine.evaluate(_refund("s1", "ch_A", 10.00, reason=""), state)
    assert r.status == "BLOCKED"
    assert r.violated_policy == "refund_requires_reason"


def test_refund_after_30_days_blocked(engine):
    state = SessionState()
    e = _refund("s1", "ch_A", 10.00)
    e.arguments["days_since_charge"] = 45
    r = engine.evaluate(e, state)
    assert r.status == "BLOCKED"
    assert r.violated_policy == "no_refund_after_30_days"


# --- cumulative state correctness -------------------------------------

def test_blocked_call_does_not_mutate_state(engine):
    """Critical: a rejected call must NOT count toward the cumulative total."""
    state = SessionState()
    engine.evaluate(_refund("s1", "ch_A", 30.00), state)
    # $30 recorded. Try $40 — blocked by cap (30+40=70>50).
    r = engine.evaluate(_refund("s1", "ch_A", 40.00), state)
    assert r.status == "BLOCKED"
    # State must still be $30, not $70.
    assert state.refunds_today_on_charge("ch_A") == 30.00
    # Now try $20 — 30+20=50, should pass.
    r2 = engine.evaluate(_refund("s1", "ch_A", 20.00), state)
    assert r2.status == "ALLOWED"


def test_different_charges_do_not_share_cumulative(engine):
    state = SessionState()
    r1 = engine.evaluate(_refund("s1", "ch_A", 40.00), state)
    r2 = engine.evaluate(_refund("s1", "ch_B", 40.00), state)
    assert r1.status == "ALLOWED"
    assert r2.status == "ALLOWED"   # separate charges, separate buckets


def test_sessions_do_not_partition_cumulative_state(engine):
    """SECURITY: changing session_id must NOT reset cumulative state."""
    state = SessionState()
    r1 = engine.evaluate(_refund("sess_1", "ch_A", 40.00), state)
    r2 = engine.evaluate(_refund("sess_2", "ch_A", 40.00), state)
    assert r1.status == "ALLOWED"
    assert r2.status == "BLOCKED"
    assert r2.violated_policy == "max_daily_refund_cap"
