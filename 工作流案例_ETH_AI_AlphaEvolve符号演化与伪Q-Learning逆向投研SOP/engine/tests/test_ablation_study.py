import unittest
from strategy_engine.ablation.ablation_suite import AblationSuite

class TestAblationStudy(unittest.TestCase):
    def test_ablation_matrix_significance(self):
        base_metrics = {
            'sharpe': 0.76,
            'win_rate': 0.8235,
            'max_drawdown': 0.1183,
            'cagr': 0.4922,
            'calmar': 4.16
        }
        suite = AblationSuite(base_metrics)
        res = suite.run_ablation_matrix()
        
        self.assertIn('BASELINE', res)
        self.assertIn('Ablation-A', res)
        self.assertIn('Ablation-D', res)
        
        # Verify that Ablation-A (w/o Q-State) leads to significant Sharpe degradation
        self.assertLess(res['Ablation-A']['delta_sharpe'], -0.30)
        self.assertLess(res['Ablation-A']['p_value'], 0.05)
        
        # Verify that Ablation-D (w/o hard SL) explodes drawdown > 50%
        self.assertGreater(res['Ablation-D']['max_drawdown'], 0.50)

if __name__ == '__main__':
    unittest.main()
