import unittest
import numpy as np
from strategy_engine.models.pure_numpy_transformer import PureNumpyCausalTransformer

class TestPureNumpyTransformer(unittest.TestCase):
    def test_causal_masking_no_future_leakage(self):
        """
        Verify that adding future rows does not change the transformer output
        at any preceding time step t.
        """
        model = PureNumpyCausalTransformer(d_in=4, d_model=8, n_heads=2)
        
        np.random.seed(123)
        X_full = np.random.randn(50, 4)
        out_full = model.forward(X_full)
        
        X_sub = X_full[:25, :]
        out_sub = model.forward(X_sub)
        
        # Check that outputs up to step 25 are strictly identical
        diff = np.max(np.abs(out_full[:25] - out_sub))
        self.assertLess(diff, 1e-10, f"Future leakage in causal attention! Diff: {diff}")

if __name__ == '__main__':
    unittest.main()
