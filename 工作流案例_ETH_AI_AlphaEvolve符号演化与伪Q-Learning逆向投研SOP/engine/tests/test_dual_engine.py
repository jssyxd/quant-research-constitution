import unittest
import json
from strategy_engine.backtest.dual_engine_reconciler import DualEngineReconciler

class TestDualEngineReconciler(unittest.TestCase):
    def test_reconcile_october_audit(self):
        with open('strategy_engine/october_750u_dual_engine_audit.json') as f:
            data = json.load(f)
            
        reconciler = DualEngineReconciler()
        res = reconciler.reconcile(data['trades_vbt'], data['trades_nau'])
        
        self.assertTrue(res['is_aligned'])
        self.assertGreater(res['direction_alignment_ratio'], 0.90)
        self.assertLess(res['avg_margin_deviation_usdt'], 1.0)
        print(f"\n[Test] Dual engine reconciliation passed: Direction Align={res['direction_alignment_ratio']*100:.1f}%, Avg Margin Dev={res['avg_margin_deviation_usdt']:.2f}U")

if __name__ == '__main__':
    unittest.main()
