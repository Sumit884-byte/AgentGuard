
import unittest

from simulator.mock_tools import Simulator
from evaluator.engine import evaluate_run
from evaluator.financial import calculate_exposure


class TestAgentGuard(unittest.TestCase):

    def test_naive_agent_detects_violation(self):
        sim = Simulator(spending_limit=100)
        sim.purchase(amount=200, protected=False)
        result = evaluate_run(sim.tool_history, sim.get_state())

        self.assertFalse(result["passed"])
        self.assertIn("Spending limit exceeded", result["violations"])

    def test_protected_agent_blocks_violation(self):
        sim = Simulator(spending_limit=100)
        event = sim.purchase(amount=200, protected=True)
        result = evaluate_run(sim.tool_history, sim.get_state())

        self.assertFalse(event["executed"])
        self.assertTrue(result["passed"])
        self.assertEqual(sim.get_state()["balance_spent"], 0)

    def test_safe_purchase_passes(self):
        sim = Simulator(spending_limit=100)
        sim.purchase(amount=50, protected=True)
        result = evaluate_run(sim.tool_history, sim.get_state())

        self.assertTrue(result["passed"])
        self.assertEqual(sim.get_state()["balance_spent"], 50)

    def test_financial_exposure(self):
        history = [
            {
                "tool": "purchase",
                "amount": 200,
                "protected": False,
                "executed": True,
                "reason": None,
            },
            {
                "tool": "purchase",
                "amount": 300,
                "protected": True,
                "executed": False,
                "reason": "Spending limit exceeded",
            },
        ]

        result = calculate_exposure(history, spending_limit=100)

        self.assertEqual(result["estimated_exposure"], 200.0)
        self.assertEqual(len(result["confirmed_violations"]), 1)

    def test_detects_final_state_mismatch(self):
        history = [
            {
                "tool": "purchase",
                "amount": 50,
                "protected": True,
                "executed": True,
                "reason": None,
            }
        ]

        final_state = {
            "spending_limit": 100,
            "balance_spent": 30,
        }

        result = evaluate_run(history, final_state)

        self.assertFalse(result["passed"])
        self.assertIn(
            "Final state does not match tool history",
            result["violations"],
        )

    def test_protected_agent_rejects_negative_purchase(self):
        sim = Simulator(spending_limit=100)
        event = sim.purchase(amount=-20, protected=True)
        result = evaluate_run(sim.tool_history, sim.get_state())

        self.assertFalse(event["executed"])
        self.assertEqual(sim.get_state()["balance_spent"], 0)
        self.assertTrue(result["passed"])

    def test_detects_executed_purchase_despite_block_reason(self):
        history = [
            {
                "tool": "purchase",
                "amount": 200,
                "protected": True,
                "executed": True,
                "reason": "Spending limit exceeded",
            }
        ]

        final_state = {
            "spending_limit": 100,
            "balance_spent": 200,
        }

        result = evaluate_run(history, final_state)

        self.assertFalse(result["passed"])
        self.assertIn("Spending limit exceeded", result["violations"])


if __name__ == "__main__":
    unittest.main()
