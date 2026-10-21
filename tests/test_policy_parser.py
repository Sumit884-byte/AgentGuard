"""Tests for the YAML policy parser."""
from pathlib import Path

import pytest

from agentguard.policy import PolicyParseError, load_policies


POLICY_FILE = Path(__file__).parent.parent / "agentguard/policy/policies/stripe.yaml"


def test_loads_stripe_policies_in_order():
    rules = load_policies(POLICY_FILE)
    assert [r.name for r in rules] == [
        "max_single_refund", "max_daily_refund_cap",
        "refund_requires_reason", "no_refund_after_30_days",
    ]
    assert all("issue_refund" in r.applies_to for r in rules)


def test_missing_file_raises(tmp_path):
    with pytest.raises(PolicyParseError, match="not found"):
        load_policies(tmp_path / "nope.yaml")


def test_bad_yaml_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("policies: [")
    with pytest.raises(PolicyParseError, match="Invalid YAML"):
        load_policies(p)


def test_missing_top_level_key_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("rules: []")
    with pytest.raises(PolicyParseError, match="policies"):
        load_policies(p)


def test_duplicate_name_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "policies:\n"
        "  - name: a_rule\n    applies_to: [issue_refund]\n    condition: 'x <= 1'\n"
        "  - name: a_rule\n    applies_to: [issue_refund]\n    condition: 'x <= 2'\n"
    )
    with pytest.raises(PolicyParseError, match="duplicate"):
        load_policies(p)


def test_missing_required_field_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("policies:\n  - name: no_condition\n    applies_to: [issue_refund]\n")
    with pytest.raises(PolicyParseError, match="invalid"):
        load_policies(p)


def test_bad_name_pattern_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("policies:\n  - name: BadName\n    applies_to: [issue_refund]\n    condition: 'x <= 1'\n")
    with pytest.raises(PolicyParseError, match="invalid"):
        load_policies(p)
