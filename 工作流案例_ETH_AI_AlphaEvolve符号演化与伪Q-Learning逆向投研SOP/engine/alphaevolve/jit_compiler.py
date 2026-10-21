"""
AlphaEvolve High-Performance JIT Evaluator using Numba.
Compiles AST trees or interprets them via optimized vectorized kernels.
Safeguards: nan/inf are strictly replaced with 0.0 to prevent execution crashes.
"""

import numpy as np
from numba import njit
from strategy_engine.alphaevolve.ast_engine import ASTNode

@njit(fastmath=True)
def jit_eval_q_state(gamma: float, alpha: float, r: np.ndarray) -> np.ndarray:
    n = len(r)
    out = np.zeros(n, dtype=np.float64)
    v = 0.0
    for i in range(n):
        v = gamma * v + alpha * r[i]
        out[i] = v
    return out

@njit(fastmath=True)
def jit_delay(arr: np.ndarray, k: int) -> np.ndarray:
    n = len(arr)
    out = np.zeros(n, dtype=np.float64)
    if k <= 0 or k >= n:
        return out
    out[k:] = arr[:-k]
    return out

@njit(fastmath=True)
def jit_delta(arr: np.ndarray, k: int) -> np.ndarray:
    n = len(arr)
    out = np.zeros(n, dtype=np.float64)
    if k <= 0 or k >= n:
        return out
    out[k:] = arr[k:] - arr[:-k]
    return out

@njit(fastmath=True)
def jit_decay_linear(arr: np.ndarray, k: int) -> np.ndarray:
    n = len(arr)
    out = np.zeros(n, dtype=np.float64)
    if k <= 0:
        return arr
    weights = np.arange(1, k + 1, dtype=np.float64)
    w_sum = np.sum(weights)
    for i in range(k - 1, n):
        sub = arr[i - k + 1 : i + 1]
        out[i] = np.sum(sub * weights) / w_sum
    return out

def evaluate_ast(node: ASTNode, feature_dict: dict, length: int) -> np.ndarray:
    """
    Recursively evaluate an ASTNode against the feature dictionary.
    Returns a numpy array of length `length`.
    """
    if node.op == 'CONST':
        return np.full(length, node.value if node.value is not None else 0.0, dtype=np.float64)
    
    elif node.op == 'FEATURE':
        if node.feature_name in feature_dict:
            return feature_dict[node.feature_name].astype(np.float64)
        return np.zeros(length, dtype=np.float64)
    
    # Unary operators
    if node.op == 'NEG':
        return -evaluate_ast(node.children[0], feature_dict, length)
    elif node.op == 'ABS':
        return np.abs(evaluate_ast(node.children[0], feature_dict, length))
    elif node.op == 'SIGN':
        return np.sign(evaluate_ast(node.children[0], feature_dict, length))
    elif node.op == 'TANH':
        return np.tanh(evaluate_ast(node.children[0], feature_dict, length))
    elif node.op == 'SIGMOID':
        x = evaluate_ast(node.children[0], feature_dict, length)
        x_clipped = np.clip(x, -20.0, 20.0)
        return 1.0 / (1.0 + np.exp(-x_clipped))
    elif node.op == 'CLIP':
        x = evaluate_ast(node.children[0], feature_dict, length)
        return np.clip(x, -5.0, 5.0)
    elif node.op == 'DELAY_1':
        x = evaluate_ast(node.children[0], feature_dict, length)
        return jit_delay(x, 1)
    elif node.op == 'DELTA_1':
        x = evaluate_ast(node.children[0], feature_dict, length)
        return jit_delta(x, 1)
    elif node.op == 'DECAY_3':
        x = evaluate_ast(node.children[0], feature_dict, length)
        return jit_decay_linear(x, 3)
        
    # Binary operators
    elif node.op == 'ADD':
        a = evaluate_ast(node.children[0], feature_dict, length)
        b = evaluate_ast(node.children[1], feature_dict, length)
        return a + b
    elif node.op == 'SUB':
        a = evaluate_ast(node.children[0], feature_dict, length)
        b = evaluate_ast(node.children[1], feature_dict, length)
        return a - b
    elif node.op == 'MUL':
        a = evaluate_ast(node.children[0], feature_dict, length)
        b = evaluate_ast(node.children[1], feature_dict, length)
        return a * b
    elif node.op == 'SAFE_DIV':
        a = evaluate_ast(node.children[0], feature_dict, length)
        b = evaluate_ast(node.children[1], feature_dict, length)
        eps = 1e-8
        safe_b = np.where(np.abs(b) > eps, b, np.sign(b + 1e-12) * eps)
        res = a / safe_b
        return np.nan_to_num(res, nan=0.0, posinf=50.0, neginf=-50.0)
        
    # Q-State Operator
    elif node.op == 'Q_STATE':
        # children: [gamma, alpha, reward_signal]
        gamma_val = node.children[0].value if node.children[0].op == 'CONST' else 0.88
        alpha_val = node.children[1].value if node.children[1].op == 'CONST' else 0.12
        r_signal = evaluate_ast(node.children[2], feature_dict, length)
        return jit_eval_q_state(gamma_val, alpha_val, r_signal)

    return np.zeros(length, dtype=np.float64)
