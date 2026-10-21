import unittest
from strategy_engine.alphaevolve.fitness import calculate_fitness
from strategy_engine.alphaevolve.walk_forward import PurgedWalkForwardMatrix

class TestWalkForward(unittest.TestCase):
    def test_fitness_drawdown_penalty(self):
        fit1 = calculate_fitness(cagr=0.49, win_rate=0.82, calmar=4.16, max_drawdown=0.118, node_count=6)
        fit2 = calculate_fitness(cagr=0.49, win_rate=0.82, calmar=4.16, max_drawdown=0.300, node_count=6)
        
        self.assertGreater(fit1, fit2)
        self.assertGreater(fit1 - fit2, 1.0)

    def test_purged_walk_forward_splits(self):
        wfo = PurgedWalkForwardMatrix(is_bars=8640, oos_bars=2880, step_bars=2880, purge_bars=20, embargo_bars=10)
        slices = wfo.split(total_bars=25000)
        self.assertGreater(len(slices), 3)
        for s in slices:
            # Check IS ends before OOS starts by at least purge_bars
            self.assertEqual(s['is'][1] + 20, s['oos'][0])
            self.assertEqual(s['purge_buffer'][1] - s['purge_buffer'][0], 20)
            self.assertEqual(s['is'][1] - s['is'][0], 8640)
            self.assertEqual(s['oos'][1] - s['oos'][0], 2880)

if __name__ == '__main__':
    unittest.main()
