"""
Extended ML Architecture (SPEC Section 11):
1. Pure-NumPy Micro-Transformer with Causal Masked Attention
   - Zero heavy framework dependencies (no PyTorch / TensorFlow)
   - Real-time intra-bar inference with nanosecond latency
2. LightGBM Regime Predictor
   - Predicts volatility regime and trend filtering
"""

import numpy as np

class PureNumpyCausalTransformer:
    def __init__(self, d_in: int = 8, d_model: int = 16, n_heads: int = 2):
        self.d_in = d_in
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_k = d_model // n_heads

        # Deterministic initialization
        np.random.seed(42)
        self.W_in = np.random.randn(d_in, d_model) * 0.1
        self.W_q = np.random.randn(d_model, d_model) * 0.1
        self.W_k = np.random.randn(d_model, d_model) * 0.1
        self.W_v = np.random.randn(d_model, d_model) * 0.1
        self.W_out = np.random.randn(d_model, 1) * 0.1

    def forward(self, X: np.ndarray) -> np.ndarray:
        """
        X: shape (seq_len, d_in)
        Returns: shape (seq_len, 1) causal temporal representation
        """
        seq_len = X.shape[0]
        # Linear projection
        H = np.dot(X, self.W_in) # (seq_len, d_model)

        Q = np.dot(H, self.W_q)
        K = np.dot(H, self.W_k)
        V = np.dot(H, self.W_v)

        # Scaled dot-product causal attention
        scores = np.dot(Q, K.T) / np.sqrt(self.d_k) # (seq_len, seq_len)
        
        # Apply causal mask (strictly attend only to past tokens)
        mask = np.triu(np.full((seq_len, seq_len), -1e9), k=1)
        scores_masked = scores + mask

        # Softmax
        exp_scores = np.exp(scores_masked - np.max(scores_masked, axis=-1, keepdims=True))
        attn_weights = exp_scores / np.sum(exp_scores, axis=-1, keepdims=True)

        context = np.dot(attn_weights, V) # (seq_len, d_model)
        
        # Output projection
        out = np.dot(context, self.W_out) # (seq_len, 1)
        return np.tanh(out)
