import unittest

from agentguard.evaluator.financial import calculate_exposure
from agentguard.evaluator.spending import evaluate_run
from agentguard.simulator.spending_demo import Simulator


class TestSpendingDemo(unittest.TestCase):
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
        history = [{"tool": "purchase", "amount": 200, "executed": True}, {"tool": "purchase", "amount": 300, "executed": False}]
        result = calculate_exposure(history, spending_limit=100)
        self.assertEqual(result["estimated_exposure"], 200.0)
        self.assertEqual(len(result["confirmed_violations"]), 1)

    def test_detects_final_state_mismatch(self):
        history = [{"tool": "purchase", "amount": 50, "executed": True}]
        result = evaluate_run(history, {"spending_limit": 100, "balance_spent": 30})
        self.assertFalse(result["passed"])
        self.assertIn("Final state does not match tool history", result["violations"])

    def test_protected_agent_rejects_negative_purchase(self):
        sim = Simulator(spending_limit=100)
        event = sim.purchase(amount=-20, protected=True)
        result = evaluate_run(sim.tool_history, sim.get_state())
        self.assertFalse(event["executed"])
        self.assertEqual(sim.get_state()["balance_spent"], 0)
        self.assertTrue(result["passed"])

    def test_detects_executed_over_limit_purchase(self):
        result = evaluate_run([{"tool": "purchase", "amount": 200, "executed": True}], {"spending_limit": 100, "balance_spent": 200})
        self.assertIn("Spending limit exceeded", result["violations"])

    def test_unprotected_non_finite_amount_is_not_executed(self):
        sim = Simulator()
        event = sim.purchase(float("nan"), protected=False)
        self.assertFalse(event["executed"])
        self.assertEqual(sim.get_state()["balance_spent"], 0)


if __name__ == "__main__":
    unittest.main()
