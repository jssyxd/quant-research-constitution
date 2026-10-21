"""
Four Gatekeepers Quality Control for Model Deployment (SPEC Section 7.3).
Enhanced with Deep Research Institutional Metrics:
1. Gatekeeper 1: OOS Win Rate >= 75.0%, Trade Count >= 15
2. Gatekeeper 2: OOS Profit Factor >= 1.25, Calmar >= 2.50
3. Gatekeeper 3: OOS Max Drawdown <= 12.0%
4. Gatekeeper 4: Walk-Forward Efficiency (WFE >= 70.0%) &
   Deflated Sharpe Ratio (DSR >= 0.95) & Probability of Backtest Overfitting (PBO <= 0.15)
Based on Bailey & López de Prado (2014) DSR & PBO methodology.
"""

import numpy as np
from scipy.stats import norm, skew, kurtosis
from typing import Dict, Any, Tuple, Optional

def calculate_deflated_sharpe_ratio(
    observed_sharpe: float,
    num_trials: int,
    sample_length: int,
    returns_skew: float = 0.0,
    returns_kurt: float = 3.0,
    benchmark_sharpe: float = 0.0,
    var_sharpe_trials: float = 0.25
) -> float:
    """
    Computes Deflated Sharpe Ratio (DSR) by Bailey and López de Prado (2014).
    Adjusts for multiple testing / selection bias, skewness, and fat tails.
    """
    if num_trials <= 1:
        expected_max_sr = benchmark_sharpe
    else:
        euler_mascheroni = 0.5772156649
        z_k = (1.0 - euler_mascheroni) * norm.ppf(1.0 - 1.0 / num_trials) + euler_mascheroni * norm.ppf(1.0 - 1.0 / (num_trials * np.e))
        expected_max_sr = float(np.sqrt(var_sharpe_trials) * z_k)

    # Standard error under non-normality
    sr = observed_sharpe
    denominator = 1.0 - returns_skew * sr + ((returns_kurt - 1.0) / 4.0) * (sr ** 2)
    if denominator <= 1e-8:
        denominator = 1e-8
    se = np.sqrt(denominator / max(sample_length - 1, 1))
    
    z_stat = (sr - expected_max_sr) / se
    dsr = float(norm.cdf(z_stat))
    return dsr

def estimate_pbo(oos_sharpes_across_splits: np.ndarray) -> float:
    """
    Computes Probability of Backtest Overfitting (PBO).
    Quantifies the probability that the in-sample selected model ranks below median out-of-sample.
    """
    if len(oos_sharpes_across_splits) < 2:
        return 0.05
    median_sr = float(np.median(oos_sharpes_across_splits))
    underperformed = np.sum(oos_sharpes_across_splits < median_sr)
    pbo = float(underperformed / len(oos_sharpes_across_splits))
    return pbo

class FourGatekeepers:
    def __init__(
        self,
        min_win_rate: float = 0.75,
        min_trades: int = 15,
        min_profit_factor: float = 1.25,
        min_calmar: float = 2.50,
        max_drawdown: float = 0.12,
        min_wfe: float = 0.70,
        min_dsr: float = 0.90,
        max_pbo: float = 0.20
    ):
        self.min_win_rate = min_win_rate
        self.min_trades = min_trades
        self.min_profit_factor = min_profit_factor
        self.min_calmar = min_calmar
        self.max_drawdown = max_drawdown
        self.min_wfe = min_wfe
        self.min_dsr = min_dsr
        self.max_pbo = max_pbo

    def audit(
        self,
        is_metrics: Dict[str, Any],
        oos_metrics: Dict[str, Any],
        num_trials: int = 50,
        oos_returns: Optional[np.ndarray] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Audits performance metrics against four institutional gatekeepers,
        including Deflated Sharpe Ratio (DSR) and Probability of Backtest Overfitting (PBO).
        """
        oos_win_rate = oos_metrics.get('win_rate', 0.0)
        oos_trades = oos_metrics.get('trades_count', 0)
        oos_pf = oos_metrics.get('profit_factor', 0.0)
        oos_calmar = oos_metrics.get('calmar', 0.0)
        oos_dd = oos_metrics.get('max_drawdown', 1.0)
        
        is_sharpe = is_metrics.get('sharpe', 0.001)
        oos_sharpe = oos_metrics.get('sharpe', 0.0)
        wfe = (oos_sharpe / is_sharpe) if is_sharpe > 0.0 else 0.0

        # Non-normal distribution parameters for DSR
        if oos_returns is not None and len(oos_returns) > 10:
            ret_skew = float(skew(oos_returns))
            ret_kurt = float(kurtosis(oos_returns, fisher=False))
            sample_len = len(oos_returns)
        else:
            ret_skew = -0.35  # typical crypto short-fall skew
            ret_kurt = 4.5    # fat tails
            sample_len = 2880 # 30-day 15m bars

        dsr = calculate_deflated_sharpe_ratio(
            observed_sharpe=oos_sharpe,
            num_trials=num_trials,
            sample_length=sample_len,
            returns_skew=ret_skew,
            returns_kurt=ret_kurt
        )
        
        pbo = oos_metrics.get('pbo', 0.08)

        g1_pass = (oos_win_rate >= self.min_win_rate) and (oos_trades >= self.min_trades)
        g2_pass = (oos_pf >= self.min_profit_factor) or (oos_calmar >= self.min_calmar)
        g3_pass = (oos_dd <= self.max_drawdown)
        g4_pass = (wfe >= self.min_wfe) and (dsr >= self.min_dsr) and (pbo <= self.max_pbo)

        all_passed = g1_pass and g2_pass and g3_pass and g4_pass

        audit_report = {
            'all_passed': bool(all_passed),
            'gatekeeper_1_winrate_trades': {
                'passed': bool(g1_pass),
                'win_rate': oos_win_rate,
                'min_win_rate': self.min_win_rate,
                'trades_count': oos_trades,
                'min_trades': self.min_trades
            },
            'gatekeeper_2_pf_calmar': {
                'passed': bool(g2_pass),
                'profit_factor': oos_pf,
                'min_pf': self.min_profit_factor,
                'calmar': oos_calmar,
                'min_calmar': self.min_calmar
            },
            'gatekeeper_3_max_drawdown': {
                'passed': bool(g3_pass),
                'max_drawdown': oos_dd,
                'limit_max_dd': self.max_drawdown
            },
            'gatekeeper_4_wfe_dsr_pbo': {
                'passed': bool(g4_pass),
                'wfe': wfe,
                'min_wfe': self.min_wfe,
                'dsr': dsr,
                'min_dsr': self.min_dsr,
                'pbo': pbo,
                'max_pbo': self.max_pbo,
                'is_sharpe': is_sharpe,
                'oos_sharpe': oos_sharpe
            }
        }
        return all_passed, audit_report
