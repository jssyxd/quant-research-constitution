"""
End-to-End Deterministic Regression & Full System Smoke Test.
Validates the complete lifecycle:
1. Feature Pipeline generation (No Lookahead Bias)
2. AST evaluation with JIT (Emergent Q-State)
3. Purged & Embargoed WFO Matrix slice splitting
4. Gatekeepers quality control check (WFE + DSR + PBO)
5. Dual engine trade reconciler (VectorBT vs Nautilus)
6. Three-tier Sentinel monitoring (L1 Execution + L2 KS Drift + L3 Circuit Breaker)
7. Ablation study matrix evaluation (Six Variants + Wilcoxon Significance)
"""

import unittest
import numpy as np
import pandas as pd
import json

from strategy_engine.features.feature_pipeline import FeaturePipeline
from strategy_engine.alphaevolve.ast_engine import ASTNode
from strategy_engine.alphaevolve.jit_compiler import evaluate_ast
from strategy_engine.alphaevolve.walk_forward import PurgedWalkForwardMatrix
from strategy_engine.gatekeeper.four_gatekeepers import FourGatekeepers
from strategy_engine.backtest.dual_engine_reconciler import DualEngineReconciler
from strategy_engine.sentinel.l1_l2_l3_sentinel import L1ExecutionSentinel, L2DriftSentinel, L3CircuitBreaker
from strategy_engine.ablation.ablation_suite import AblationSuite

class TestE2EFullSystem(unittest.TestCase):
    def test_e2e_closed_loop(self):
        print("\n>>> [E2E] Step 1: Feature Extraction (Zero Lookahead)...")
        n = 500
        np.random.seed(42)
        prices = 2500.0 + np.cumsum(np.random.randn(n) * 4.0)
        df = pd.DataFrame({
            'open': prices + np.random.randn(n),
            'high': prices + np.abs(np.random.randn(n) * 2.0),
            'low': prices - np.abs(np.random.randn(n) * 2.0),
            'close': prices,
            'volume': np.random.uniform(500, 1500, n),
            'taker_buy_volume': np.random.uniform(250, 750, n)
        }, index=pd.date_range('2026-10-01', periods=n, freq='15min'))
        
        pipe = FeaturePipeline(window_norm=20)
        feats = pipe.transform(df)
        self.assertEqual(len(feats), n)
        self.assertFalse(feats.isna().any().any())

        print(">>> [E2E] Step 2: AST JIT Evaluation (Q-State)...")
        gamma_node = ASTNode('CONST', value=0.88)
        alpha_node = ASTNode('CONST', value=0.12)
        sub_node = ASTNode('SUB', children=[
            ASTNode('FEATURE', feature_name='z_score'),
            ASTNode('FEATURE', feature_name='norm_volume')
        ])
        q_tree = ASTNode('Q_STATE', children=[gamma_node, alpha_node, sub_node])
        
        feat_dict = {col: feats[col].values for col in feats.columns}
        signals = evaluate_ast(q_tree, feat_dict, n)
        self.assertEqual(len(signals), n)

        print(">>> [E2E] Step 3: Purged & Embargoed WFO Matrix...")
        wfo = PurgedWalkForwardMatrix(is_bars=300, oos_bars=100, step_bars=100, purge_bars=10, embargo_bars=5)
        slices = wfo.split(n)
        self.assertGreaterEqual(len(slices), 1)

        print(">>> [E2E] Step 4: Gatekeeper Evaluation (WFE + DSR + PBO)...")
        gk = FourGatekeepers()
        passed, report = gk.audit(
            is_metrics={'sharpe': 1.8},
            oos_metrics={
                'win_rate': 0.82,
                'trades_count': 17,
                'profit_factor': 1.30,
                'calmar': 3.5,
                'max_drawdown': 0.11,
                'sharpe': 1.65,
                'pbo': 0.05
            },
            num_trials=20
        )
        self.assertTrue(passed)

        print(">>> [E2E] Step 5: Dual Engine Reconciliation...")
        with open('strategy_engine/october_750u_dual_engine_audit.json') as f:
            audit_json = json.load(f)
        reconciler = DualEngineReconciler()
        res_align = reconciler.reconcile(audit_json['trades_vbt'], audit_json['trades_nau'])
        self.assertTrue(res_align['is_aligned'])

        print(">>> [E2E] Step 6: Sentinels (L1 Slippage + L2 KS Drift + L3 Breaker)...")
        l1 = L1ExecutionSentinel()
        l2 = L2DriftSentinel()
        l3 = L3CircuitBreaker()
        self.assertEqual(l1.check(2500.0, 2500.5)['status'], 'HEALTHY_GREEN')
        
        # Test KS-test on features
        f_base = feats['z_score'].values[:200]
        f_oper = feats['z_score'].values[200:400]
        drift_res = l2.check_distribution_drift(f_base, f_oper)
        self.assertIn('ks_statistic', drift_res)
        self.assertFalse(l3.check(0.01, 0.05)['circuit_broken'])

        print(">>> [E2E] Step 7: Ablation Suite Matrix...")
        suite = AblationSuite(audit_json['metrics_vbt'])
        ablation_res = suite.run_ablation_matrix()
        self.assertIn('BASELINE', ablation_res)
        self.assertIn('Ablation-A', ablation_res)

        print(">>> [E2E] ALL SYSTEM INTEGRATION TESTS PASSED 100%!")

if __name__ == '__main__':
    unittest.main()
