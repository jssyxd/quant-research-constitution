"""
Multi-Objective Composite Fitness Formulation.
Fitness = CAGR * WinRate * Calmar - 15.0 * (MaxDrawdown)^2 - lambda * NodeCount
Enforces quadratic drawdown penalty and Occam's razor simplicity pressure.
"""

import numpy as np

def calculate_fitness(
    cagr: float,
    win_rate: float,
    calmar: float,
    max_drawdown: float,
    node_count: int,
    lambda_parsimony: float = 0.01,
    dd_penalty_weight: float = 15.0
) -> float:
    """
    Computes fitness score with non-linear drawdown penalty.
    cagr: e.g. 0.45 (+45%)
    win_rate: e.g. 0.82 (82%)
    calmar: e.g. 3.5
    max_drawdown: e.g. 0.118 (11.8%)
    node_count: number of nodes in AST
    """
    # Base positive reward
    base_reward = max(cagr, -1.0) * win_rate * max(calmar, 0.0)
    
    # Quadratic drawdown penalty
    dd_penalty = dd_penalty_weight * (max_drawdown ** 2)
    
    # Occam's razor complexity penalty
    complexity_penalty = lambda_parsimony * node_count
    
    fitness = base_reward - dd_penalty - complexity_penalty
    return float(fitness)
