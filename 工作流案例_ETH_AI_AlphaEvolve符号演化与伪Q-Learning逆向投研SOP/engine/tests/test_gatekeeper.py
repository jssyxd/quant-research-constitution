import unittest
from strategy_engine.gatekeeper.four_gatekeepers import FourGatekeepers

class TestFourGatekeepers(unittest.TestCase):
    def setUp(self):
        self.gk = FourGatekeepers()

    def test_passing_candidate(self):
        is_metrics = {'sharpe': 2.0}
        oos_metrics = {
            'win_rate': 0.80,
            'trades_count': 18,
            'profit_factor': 1.35,
            'calmar': 3.2,
            'max_drawdown': 0.10,
            'sharpe': 1.60 # WFE = 1.6 / 2.0 = 0.80 >= 0.70
        }
        passed, report = self.gk.audit(is_metrics, oos_metrics)
        self.assertTrue(passed)
        self.assertTrue(report['all_passed'])

    def test_overfitting_rejection(self):
        # Severe degradation (PBO / low WFE)
        is_metrics = {'sharpe': 3.5}
        oos_metrics = {
            'win_rate': 0.78,
            'trades_count': 20,
            'profit_factor': 1.26,
            'calmar': 2.6,
            'max_drawdown': 0.11,
            'sharpe': 1.0 # WFE = 1.0 / 3.5 = 0.285 < 0.70
        }
        passed, report = self.gk.audit(is_metrics, oos_metrics)
        self.assertFalse(passed)
        self.assertFalse(report['gatekeeper_4_wfe']['passed'])

if __name__ == '__main__':
    unittest.main()
