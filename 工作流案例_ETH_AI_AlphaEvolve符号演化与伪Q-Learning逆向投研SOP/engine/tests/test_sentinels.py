import unittest
import numpy as np
from strategy_engine.sentinel.l1_l2_l3_sentinel import L1ExecutionSentinel, L2DriftSentinel, L3CircuitBreaker

class TestSentinels(unittest.TestCase):
    def test_l1_execution_slippage(self):
        l1 = L1ExecutionSentinel(max_slippage_bps=3.0, max_consecutive_slippage_violations=3)
        res1 = l1.check(2500.0, 2501.0) # 4 bps
        self.assertEqual(res1['status'], 'HEALTHY_GREEN')
        res2 = l1.check(2500.0, 2501.0)
        res3 = l1.check(2500.0, 2501.0)
        self.assertEqual(res3['status'], 'WARNING_YELLOW')

    def test_l2_ks_test_distribution_drift(self):
        l2 = L2DriftSentinel(ks_p_value_threshold=0.01)
        # Identical distribution
        np.random.seed(42)
        base = np.random.normal(0, 1, 500)
        oper_same = np.random.normal(0, 1, 500)
        res_same = l2.check_distribution_drift(base, oper_same)
        self.assertFalse(res_same['drift_detected'])
        self.assertEqual(res_same['status'], 'DISTRIBUTION_STABLE_GREEN')

        # Shifted distribution (regime shift)
        oper_shifted = np.random.normal(1.5, 2.0, 500)
        res_shifted = l2.check_distribution_drift(base, oper_shifted)
        self.assertTrue(res_shifted['drift_detected'])
        self.assertEqual(res_shifted['status'], 'DRIFT_ALERT_ORANGE')

    def test_l3_circuit_breaker(self):
        l3 = L3CircuitBreaker(daily_loss_limit=0.06, total_drawdown_limit=0.12)
        res_ok = l3.check(daily_pnl_pct=-0.02, current_total_drawdown=0.05)
        self.assertFalse(res_ok['circuit_broken'])
        res_halt = l3.check(daily_pnl_pct=-0.01, current_total_drawdown=0.125)
        self.assertTrue(res_halt['circuit_broken'])
        self.assertEqual(res_halt['status'], 'HALT_REDUCE_ONLY_RED')

if __name__ == '__main__':
    unittest.main()
