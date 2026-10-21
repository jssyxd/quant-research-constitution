import unittest
import numpy as np
import pandas as pd
from strategy_engine.features.feature_pipeline import FeaturePipeline

class TestFeaturePipeline(unittest.TestCase):
    def test_feature_pipeline_no_lookahead(self):
        """
        Test that feature values at time t are completely identical
        whether the series ends at time t or continues to t+100.
        """
        np.random.seed(42)
        n = 200
        prices = 2500.0 + np.cumsum(np.random.randn(n) * 5.0)
        highs = prices + np.abs(np.random.randn(n) * 3.0)
        lows = prices - np.abs(np.random.randn(n) * 3.0)
        opens = prices + np.random.randn(n) * 2.0
        volumes = np.random.uniform(100, 1000, n)
        taker_buy = volumes * np.random.uniform(0.3, 0.7, n)
        
        idx = pd.date_range('2026-10-01', periods=n, freq='15min')
        df_full = pd.DataFrame({
            'open': opens,
            'high': highs,
            'low': lows,
            'close': prices,
            'volume': volumes,
            'taker_buy_volume': taker_buy
        }, index=idx)
        
        pipe = FeaturePipeline(window_norm=20)
        feats_full = pipe.transform(df_full)
        
        # Sub-dataframe up to bar 100
        df_sub = df_full.iloc[:100].copy()
        feats_sub = pipe.transform(df_sub)
        
        # Check that up to bar 100, features in full and sub are strictly identical
        for col in feats_full.columns:
            diff = np.max(np.abs(feats_full[col].iloc[:100].values - feats_sub[col].values))
            self.assertLess(diff, 1e-8, f"Lookahead bias detected in feature: {col}, max diff: {diff}")

    def test_no_bfill_or_future_nans(self):
        df = pd.DataFrame({
            'open': [100.0, 101.0, 102.0],
            'high': [101.0, 102.0, 103.0],
            'low': [99.0, 100.0, 101.0],
            'close': [100.5, 101.5, 102.5],
            'volume': [500.0, 600.0, 700.0]
        })
        pipe = FeaturePipeline(window_norm=20)
        feats = pipe.transform(df)
        self.assertFalse(feats.isna().any().any(), "Features must not contain NaNs")

if __name__ == '__main__':
    unittest.main()
