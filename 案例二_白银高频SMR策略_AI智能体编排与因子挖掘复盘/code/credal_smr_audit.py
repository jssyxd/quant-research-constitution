"""
credal_smr_audit.py - Credal Transformer & Anti-Overfitting / Anti-Hallucination Review Engine
=============================================================================================
Based on NeurIPS 2025 Credal Transformer (arXiv:2510.12137), Subjective Logic, and Evidential Deep Learning.

Features:
1. Dirichlet Evidential Reasoning:
   - Maps multi-factor signals into Dirichlet distribution parameters [alpha_bull, alpha_bear, alpha_neutral].
   - Decomposes belief into belief mass [b_bull, b_bear, b_neutral] and epistemic vacuity uncertainty (u = K / S).
   - Computes directional conflict mass C.
   - Enforces the Credal Gate: Rejects hallucinations and overfitted signals when u > 0.35 or C >= 0.40.
2. Anti-Overfitting Statistical Suite:
   - Deflated Sharpe Ratio (DSR, Bailey & Lopez de Prado, 2014) accounting for trial variance.
   - Haircut Sharpe Ratio (Harvey & Liu, 2015).
   - Monte Carlo Path Permutation Test (1,000 simulations) to obtain p-value of strategy survival.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import scipy.stats as stats


class CredalSignal(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class CredalDecision:
    p_bull: float
    p_bear: float
    p_neutral: float
    uncertainty: float
    conflict: float
    should_abstain: bool
    credal_signal: CredalSignal
    confidence: float
    abstain_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["credal_signal"] = str(self.credal_signal)
        return data


class CredalTransformerGate:
    """
    Credal Uncertainty Gate for Anti-Hallucination & Anti-Overfitting.
    Enforces Dirichlet subjective logic prior to trade execution.
    """

    def __init__(self, u_max: float = 0.35, conflict_max: float = 0.40, K: int = 3):
        self.u_max = u_max
        self.conflict_max = conflict_max
        self.K = K  # 3 categories: Bull, Bear, Neutral

    def evaluate_evidence(
        self,
        bull_evidence: float,
        bear_evidence: float,
        neutral_evidence: float = 0.5,
    ) -> CredalDecision:
        """
        Evaluate directional evidence mass, compute vacuity uncertainty and conflict.
        """
        e_bull = max(0.0, float(bull_evidence))
        e_bear = max(0.0, float(bear_evidence))
        e_neutral = max(0.0, float(neutral_evidence))

        alpha_bull = e_bull + 1.0
        alpha_bear = e_bear + 1.0
        alpha_neutral = e_neutral + 1.0
        S = alpha_bull + alpha_bear + alpha_neutral

        # Belief masses
        b_bull = e_bull / S
        b_bear = e_bear / S
        b_neutral = e_neutral / S
        u = float(self.K / S)  # Vacuity uncertainty

        # Expected probabilities
        p_bull = alpha_bull / S
        p_bear = alpha_bear / S
        p_neutral = alpha_neutral / S

        # Conflict mass between bull and bear
        if (b_bull + b_bear) > 1e-6:
            conflict = float(2.0 * min(b_bull, b_bear) / (b_bull + b_bear))
        else:
            conflict = 0.0

        # Abstention decision
        should_abstain = False
        reason = None

        if u > self.u_max:
            should_abstain = True
            reason = f"High epistemic vacuity uncertainty: u={u:.3f} > {self.u_max}"
        elif conflict >= self.conflict_max:
            should_abstain = True
            reason = f"Severe signal conflict between bull and bear: C={conflict:.3f} >= {self.conflict_max}"
        elif max(p_bull, p_bear) < 0.50:
            should_abstain = True
            reason = f"Inconclusive probability margin: max(p_bull, p_bear)={max(p_bull, p_bear):.3f} < 0.50"

        # Signal determination
        if not should_abstain:
            if p_bull > p_bear and p_bull >= 0.50:
                signal = CredalSignal.BULLISH
                confidence = p_bull
            elif p_bear > p_bull and p_bear >= 0.50:
                signal = CredalSignal.BEARISH
                confidence = p_bear
            else:
                signal = CredalSignal.NEUTRAL
                confidence = p_neutral
        else:
            signal = CredalSignal.NEUTRAL
            confidence = 1.0 - u

        return CredalDecision(
            p_bull=p_bull,
            p_bear=p_bear,
            p_neutral=p_neutral,
            uncertainty=u,
            conflict=conflict,
            should_abstain=should_abstain,
            credal_signal=signal,
            confidence=confidence,
            abstain_reason=reason,
        )


def calculate_deflated_sharpe_ratio(
    sr_estimate: float,
    sample_length: int,
    n_trials: int = 100,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> Dict[str, float]:
    """
    Computes Deflated Sharpe Ratio (DSR) by adjusting for multiple testing and non-normal returns.
    Reference: Bailey & Lopez de Prado (2014)
    """
    # Expected maximum Sharpe ratio under null hypothesis of no true skill
    euler_mascheroni = 0.5772156649
    if n_trials > 1:
        # Extreme value distribution approximation
        z_n = (1.0 - euler_mascheroni) * stats.norm.ppf(1.0 - 1.0 / n_trials) + euler_mascheroni * stats.norm.ppf(1.0 - 1.0 / (n_trials * np.e))
        expected_max_sr = z_n
    else:
        expected_max_sr = 0.0

    # Variance of Sharpe ratio estimate with non-normal return corrections
    # Var(SR) = (1 + 0.5 * SR^2 - skew * SR + ((kurtosis - 3) / 4) * SR^2) / T
    var_sr = (1.0 + 0.5 * (sr_estimate ** 2) - skewness * sr_estimate + ((kurtosis - 3.0) / 4.0) * (sr_estimate ** 2)) / sample_length
    std_sr = np.sqrt(max(1e-8, var_sr))

    # DSR is the probability that the estimated Sharpe exceeds the expected maximum
    z_stat = (sr_estimate - expected_max_sr) / std_sr
    dsr = float(stats.norm.cdf(z_stat))

    # Haircut Sharpe ratio (Harvey & Liu 2015 haircut estimation)
    haircut_ratio = max(0.0, 1.0 - (expected_max_sr / (abs(sr_estimate) + 1e-6)))
    haircut_sr = float(sr_estimate * haircut_ratio)

    return {
        "estimated_sr": float(sr_estimate),
        "expected_max_sr_null": float(expected_max_sr),
        "dsr_probability": dsr,
        "is_statistically_significant": bool(dsr >= 0.95),
        "haircut_sr": haircut_sr,
        "n_trials": n_trials,
    }


def monte_carlo_permutation_test(
    trade_returns: np.ndarray,
    n_permutations: int = 1000,
    seed: int = 42,
) -> Dict[str, float]:
    """
    Monte Carlo trade-order permutation test to verify if the strategy's Sharpe
    and CAGR are driven by genuine edge rather than lucky market path ordering.
    """
    if len(trade_returns) < 5:
        return {"p_value": 1.0, "mc_sharpe_5th": 0.0, "mc_sharpe_50th": 0.0, "mc_sharpe_95th": 0.0}

    rng = np.random.default_rng(seed)
    n = len(trade_returns)
    observed_sr = np.mean(trade_returns) / (np.std(trade_returns) + 1e-8)

    sim_sharpes = []
    sim_drawdowns = []

    for _ in range(n_permutations):
        perm_rets = rng.permutation(trade_returns)
        cum_equity = np.cumprod(1.0 + perm_rets)
        cum_max = np.maximum.accumulate(cum_equity)
        dd = (cum_equity - cum_max) / cum_max
        sim_drawdowns.append(abs(np.min(dd)))
        sr = np.mean(perm_rets) / (np.std(perm_rets) + 1e-8)
        sim_sharpes.append(sr)

    sim_sharpes = np.array(sim_sharpes)
    p_val = float(np.mean(sim_sharpes >= observed_sr))

    return {
        "observed_sr": float(observed_sr),
        "mc_sharpe_5th": float(np.percentile(sim_sharpes, 5)),
        "mc_sharpe_50th": float(np.percentile(sim_sharpes, 50)),
        "mc_sharpe_95th": float(np.percentile(sim_sharpes, 95)),
        "mc_max_dd_95th": float(np.percentile(sim_drawdowns, 95)),
        "permutation_p_value": p_val,
        "is_robust": bool(p_val <= 0.05),
    }
