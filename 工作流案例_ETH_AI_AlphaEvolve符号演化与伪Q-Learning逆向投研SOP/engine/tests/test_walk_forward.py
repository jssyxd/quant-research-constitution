import unittest
from strategy_engine.alphaevolve.fitness import calculate_fitness
from strategy_engine.alphaevolve.walk_forward import WalkForwardMatrix

class TestWalkForward(unittest.TestCase):
    def test_fitness_drawdown_penalty(self):
        # Normal healthy strategy
        fit1 = calculate_fitness(cagr=0.49, win_rate=0.82, calmar=4.16, max_drawdown=0.118, node_count=6)
        # Dangerous strategy with 30% drawdown
        fit2 = calculate_fitness(cagr=0.49, win_rate=0.82, calmar=4.16, max_drawdown=0.300, node_count=6)
        
        self.assertGreater(fit1, fit2)
        # Verify quadratic penalty difference: 15 * (0.30^2 - 0.118^2) = 15 * (0.09 - 0.0139) = 1.14
        self.assertGreater(fit1 - fit2, 1.0)

    def test_walk_forward_splits(self):
        wfo = WalkForwardMatrix(is_bars=8640, oos_bars=2880, step_bars=2880)
        # Total 25,000 bars
        slices = wfo.split(total_bars=25000)
        self.assertGreater(len(slices), 3)
        # Verify no overlap between IS and OOS within same fold
        for s in slices:
            self.assertEqual(s['is'][1], s['oos'][0])
            self.assertEqual(s['is'][1] - s['is'][0], 8640)
            self.assertEqual(s['oos'][1] - s['oos'][0], 2880)

if __name__ == '__main__':
    unittest.main()
