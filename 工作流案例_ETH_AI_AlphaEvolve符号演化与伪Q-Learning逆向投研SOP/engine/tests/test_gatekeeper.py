import unittest
from strategy_engine.gatekeeper.four_gatekeepers import FourGatekeepers, calculate_deflated_sharpe_ratio

class TestFourGatekeepers(unittest.TestCase):
    def setUp(self):
        self.gk = FourGatekeepers()

    def test_passing_candidate_with_dsr(self):
        is_metrics = {'sharpe': 2.0}
        oos_metrics = {
            'win_rate': 0.80,
            'trades_count': 18,
            'profit_factor': 1.35,
            'calmar': 3.2,
            'max_drawdown': 0.10,
            'sharpe': 1.85, # WFE = 1.85 / 2.0 = 0.925 >= 0.70
            'pbo': 0.05
        }
        passed, report = self.gk.audit(is_metrics, oos_metrics, num_trials=20)
        self.assertTrue(passed)
        self.assertTrue(report['all_passed'])
        self.assertGreaterEqual(report['gatekeeper_4_wfe_dsr_pbo']['dsr'], 0.90)

    def test_overfitting_rejection_low_dsr_or_high_pbo(self):
        # Severe degradation (low OOS Sharpe after 100 trials -> DSR collapses)
        is_metrics = {'sharpe': 3.5}
        oos_metrics = {
            'win_rate': 0.76,
            'trades_count': 20,
            'profit_factor': 1.26,
            'calmar': 2.6,
            'max_drawdown': 0.11,
            'sharpe': 0.50, # very low Sharpe relative to 100 trials
            'pbo': 0.45     # high PBO
        }
        passed, report = self.gk.audit(is_metrics, oos_metrics, num_trials=100)
        self.assertFalse(passed)
        self.assertFalse(report['gatekeeper_4_wfe_dsr_pbo']['passed'])

if __name__ == '__main__':
    unittest.main()
