"""
Institutional Three-Tier AI Sentinel Surveillance System (SPEC Section 9).
Enhanced with Deep Research Continuous Training (CT) and Statistical Drift Testing:
L1: Microstructure Execution Health (Slippage, Latency, Fill Ratio)
L2: Concept Drift & Market Regime Shift:
    - 2-Sample Kolmogorov-Smirnov (K-S) statistical tests on operational vs baseline features
    - Rolling Win-Rate & Drawdown degradation triggers
L3: Circuit Breaker & Hard Capital Defense (Reduce-Only mode, Webhook cutoff)
"""

import numpy as np
from scipy.stats import ks_2samp
from typing import Dict, Any, List, Optional

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
    def __init__(
        self,
        min_rolling_win_rate: float = 0.65,
        max_rolling_drawdown: float = 0.08,
        ks_p_value_threshold: float = 0.01
    ):
        self.min_rolling_win_rate = min_rolling_win_rate
        self.max_rolling_drawdown = max_rolling_drawdown
        self.ks_p_value_threshold = ks_p_value_threshold

    def check_distribution_drift(
        self,
        baseline_features: np.ndarray,
        operational_features: np.ndarray
    ) -> Dict[str, Any]:
        """
        Runs 2-Sample Kolmogorov-Smirnov test to detect feature distribution shifts.
        """
        ks_stat, p_val = ks_2samp(baseline_features, operational_features)
        drift_detected = p_val < self.ks_p_value_threshold
        return {
            'ks_statistic': float(ks_stat),
            'p_value': float(p_val),
            'drift_detected': bool(drift_detected),
            'status': 'DRIFT_ALERT_ORANGE' if drift_detected else 'DISTRIBUTION_STABLE_GREEN'
        }

    def check(
        self,
        rolling_pnl_list: List[float],
        baseline_features: Optional[np.ndarray] = None,
        operational_features: Optional[np.ndarray] = None
    ) -> Dict[str, Any]:
        if len(rolling_pnl_list) < 10:
            return {'level': 'L2', 'status': 'WARMING_UP'}
            
        wins = sum(1 for p in rolling_pnl_list if p > 0)
        win_rate = wins / len(rolling_pnl_list)
        
        # Calculate rolling peak drawdown
        equity = np.cumsum(rolling_pnl_list)
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / (np.maximum(peak, 1.0))
        max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

        perf_trigger = (win_rate < self.min_rolling_win_rate) or (max_dd > self.max_rolling_drawdown)
        
        drift_info = None
        if baseline_features is not None and operational_features is not None:
            drift_info = self.check_distribution_drift(baseline_features, operational_features)
            ks_trigger = drift_info['drift_detected']
        else:
            ks_trigger = False

        trigger_retrain = perf_trigger or ks_trigger

        return {
            'level': 'L2',
            'rolling_win_rate': win_rate,
            'rolling_max_dd': max_dd,
            'feature_drift': drift_info,
            'trigger_retrain': bool(trigger_retrain),
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
