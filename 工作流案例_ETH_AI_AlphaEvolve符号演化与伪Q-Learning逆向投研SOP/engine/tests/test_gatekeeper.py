import unittest
import numpy as np
from strategy_engine.gatekeeper.four_gatekeepers import (
    FourGatekeepers,
    calculate_deflated_sharpe_ratio,
    calculate_min_trl,
    estimate_effective_trials
)

class TestFourGatekeepers(unittest.TestCase):
    def setUp(self):
        self.gk = FourGatekeepers()

    def test_min_trl_calculation(self):
        # A good Sharpe of 1.8 on 15m crypto requires realistic MinTRL
        min_trl = calculate_min_trl(observed_sharpe=1.8, returns_skew=-0.2, returns_kurt=4.0)
        self.assertGreater(min_trl, 1.0)
        self.assertLess(min_trl, 500.0, "High Sharpe should require modest MinTRL")
        
        # A marginal Sharpe of 0.05 requires over 1,000 bars
        min_trl_weak = calculate_min_trl(observed_sharpe=0.05)
        self.assertGreater(min_trl_weak, 1000.0)

    def test_effective_trials_eigenvalues(self):
        np.random.seed(42)
        # 10 completely independent trial returns
        ret_indep = np.random.randn(100, 10)
        k_eff_indep = estimate_effective_trials(ret_indep)
        self.assertGreaterEqual(k_eff_indep, 8)

        # 10 collinear/strongly correlated trial returns (copies with tiny noise)
        base = np.random.randn(100, 1)
        ret_corr = np.repeat(base, 10, axis=1) + np.random.randn(100, 10) * 0.01
        k_eff_corr = estimate_effective_trials(ret_corr)
        self.assertLessEqual(k_eff_corr, 2, "Correlated trials should collapse K_eff")

    def test_passing_candidate_with_dsr_and_mintr(self):
        is_metrics = {'sharpe': 2.0}
        oos_metrics = {
            'win_rate': 0.80,
            'trades_count': 18,
            'profit_factor': 1.35,
            'calmar': 3.2,
            'max_drawdown': 0.10,
            'sharpe': 1.85,
            'pbo': 0.05
        }
        passed, report = self.gk.audit(is_metrics, oos_metrics, num_trials=20)
        self.assertTrue(passed)
        self.assertTrue(report['all_passed'])
        self.assertGreaterEqual(report['gatekeeper_4_wfe_dsr_pbo_mintr']['dsr'], 0.90)
        self.assertTrue(report['gatekeeper_4_wfe_dsr_pbo_mintr']['mintr_satisfied'])

    def test_fail_closed_guard(self):
        # Missing metrics must fail closed
        passed, report = self.gk.audit(None, None)
        self.assertFalse(passed)
        self.assertIn('FAIL_CLOSED', report.get('error', ''))

if __name__ == '__main__':
    unittest.main()
