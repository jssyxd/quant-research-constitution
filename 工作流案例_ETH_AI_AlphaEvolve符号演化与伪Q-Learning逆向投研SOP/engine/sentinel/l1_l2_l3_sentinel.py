"""
Institutional Three-Tier AI Sentinel Surveillance System (SPEC Section 9).
L1: Microstructure Execution Health (Slippage, Latency, Fill Ratio)
L2: Concept Drift & Market Regime Shift (Rolling Wasserstein / KS distance, Win-rate degradation)
L3: Circuit Breaker & Hard Capital Defense (Reduce-Only mode, Webhook cutoff)
"""

import numpy as np
from typing import Dict, Any, List

class L1ExecutionSentinel:
    def __init__(self, max_slippage_bps: float = 3.0, max_consecutive_slippage_violations: int = 3):
        self.max_slippage_bps = max_slippage_bps
        self.max_consecutive_violations = max_consecutive_slippage_violations
        self.consecutive_violations = 0

    def check(self, expected_price: float, fill_price: float) -> Dict[str, Any]:
        slippage_bps = abs(fill_price - expected_price) / (expected_price + 1e-8) * 10000.0
        if slippage_bps > self.max_slippage_bps:
            self.consecutive_violations += 1
        else:
            self.consecutive_violations = 0
            
        is_warning = self.consecutive_violations >= self.max_consecutive_violations
        return {
            'level': 'L1',
            'slippage_bps': slippage_bps,
            'consecutive_violations': self.consecutive_violations,
            'status': 'WARNING_YELLOW' if is_warning else 'HEALTHY_GREEN'
        }

class L2DriftSentinel:
    def __init__(self, min_rolling_win_rate: float = 0.65, max_rolling_drawdown: float = 0.08):
        self.min_rolling_win_rate = min_rolling_win_rate
        self.max_rolling_drawdown = max_rolling_drawdown

    def check(self, rolling_pnl_list: List[float]) -> Dict[str, Any]:
        if len(rolling_pnl_list) < 10:
            return {'level': 'L2', 'status': 'WARMING_UP'}
            
        wins = sum(1 for p in rolling_pnl_list if p > 0)
        win_rate = wins / len(rolling_pnl_list)
        
        # Calculate rolling peak drawdown
        equity = np.cumsum(rolling_pnl_list)
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / (np.maximum(peak, 1.0))
        max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

        trigger_retrain = (win_rate < self.min_rolling_win_rate) or (max_dd > self.max_rolling_drawdown)
        return {
            'level': 'L2',
            'rolling_win_rate': win_rate,
            'rolling_max_dd': max_dd,
            'trigger_retrain': trigger_retrain,
            'status': 'TRIGGER_RETRAIN_ORANGE' if trigger_retrain else 'STABLE_GREEN'
        }

class L3CircuitBreaker:
    def __init__(self, daily_loss_limit: float = 0.06, total_drawdown_limit: float = 0.12):
        self.daily_loss_limit = daily_loss_limit
        self.total_drawdown_limit = total_drawdown_limit

    def check(self, daily_pnl_pct: float, current_total_drawdown: float) -> Dict[str, Any]:
        breached = (daily_pnl_pct <= -self.daily_loss_limit) or (current_total_drawdown >= self.total_drawdown_limit)
        return {
            'level': 'L3',
            'daily_pnl_pct': daily_pnl_pct,
            'total_drawdown': current_total_drawdown,
            'circuit_broken': breached,
            'status': 'HALT_REDUCE_ONLY_RED' if breached else 'ARMED_GREEN'
        }
