import unittest
from strategy_engine.sentinel.l1_l2_l3_sentinel import L1ExecutionSentinel, L2DriftSentinel, L3CircuitBreaker

class TestSentinels(unittest.TestCase):
    def test_l1_execution_slippage(self):
        l1 = L1ExecutionSentinel(max_slippage_bps=3.0, max_consecutive_slippage_violations=3)
        res1 = l1.check(2500.0, 2501.0) # 4 bps
        self.assertEqual(res1['status'], 'HEALTHY_GREEN')
        res2 = l1.check(2500.0, 2501.0)
        res3 = l1.check(2500.0, 2501.0)
        self.assertEqual(res3['status'], 'WARNING_YELLOW')

    def test_l2_drift_and_retrain(self):
        l2 = L2DriftSentinel(min_rolling_win_rate=0.65)
        # 10 trades: 5 wins, 5 losses -> win rate 50% < 65%
        pnls = [10.0, -10.0, 10.0, -10.0, 10.0, -10.0, 10.0, -10.0, 10.0, -10.0]
        res = l2.check(pnls)
        self.assertTrue(res['trigger_retrain'])
        self.assertEqual(res['status'], 'TRIGGER_RETRAIN_ORANGE')

    def test_l3_circuit_breaker(self):
        l3 = L3CircuitBreaker(daily_loss_limit=0.06, total_drawdown_limit=0.12)
        # Normal
        res_ok = l3.check(daily_pnl_pct=-0.02, current_total_drawdown=0.05)
        self.assertFalse(res_ok['circuit_broken'])
        # Drawdown limit breached
        res_halt = l3.check(daily_pnl_pct=-0.01, current_total_drawdown=0.125)
        self.assertTrue(res_halt['circuit_broken'])
        self.assertEqual(res_halt['status'], 'HALT_REDUCE_ONLY_RED')

if __name__ == '__main__':
    unittest.main()
