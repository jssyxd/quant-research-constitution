"""
AlphaEvolve AST Engine & Symbolic Regression Node Definitions.
Includes:
- Primitive Operators: Add, Sub, Mul, SafeDiv, Tanh, Sigmoid, Clip
- Time Series Operators: Delay(k), Delta(k), DecayLinear(k)
- Emergent Reinforcement Learning Q-State Operator: V(t) = gamma * V(t-1) + alpha * R(t)
- AST Node tree representation with Occam's razor complexity constraints (max depth 5, max nodes 20)
"""

import numpy as np
from typing import List, Union, Optional

class ASTNode:
    def __init__(self, op: str, children: Optional[List['ASTNode']] = None, value: Optional[float] = None, feature_name: Optional[str] = None):
        self.op = op
        self.children = children if children is not None else []
        self.value = value
        self.feature_name = feature_name

    def node_count(self) -> int:
        return 1 + sum(child.node_count() for child in self.children)

    def depth(self) -> int:
        if not self.children:
            return 1
        return 1 + max(child.depth() for child in self.children)

    def to_string(self) -> str:
        if self.op == 'CONST':
            return f"{self.value:.4f}"
        elif self.op == 'FEATURE':
            return f"{self.feature_name}"
        elif len(self.children) == 1:
            return f"{self.op}({self.children[0].to_string()})"
        elif len(self.children) == 2:
            return f"({self.children[0].to_string()} {self.op} {self.children[1].to_string()})"
        elif self.op == 'Q_STATE':
            return f"QState(gamma={self.children[0].to_string()}, alpha={self.children[1].to_string()}, r={self.children[2].to_string()})"
        return f"{self.op}({', '.join(c.to_string() for c in self.children)})"

    def __repr__(self):
        return self.to_string()

def safe_div(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    eps = 1e-8
    safe_b = np.where(np.abs(b) > eps, b, np.sign(b + 1e-12) * eps)
    res = a / safe_b
    return np.nan_to_num(res, nan=0.0, posinf=100.0, neginf=-100.0)

def q_state_step(gamma: float, alpha: float, r: np.ndarray) -> np.ndarray:
    n = len(r)
    v = np.zeros(n, dtype=np.float64)
    curr_v = 0.0
    for i in range(n):
        curr_v = gamma * curr_v + alpha * r[i]
        v[i] = curr_v
    return v
