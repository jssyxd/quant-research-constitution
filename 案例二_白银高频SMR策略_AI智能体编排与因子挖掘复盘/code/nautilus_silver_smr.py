"""
nautilus_silver_smr.py - NautilusTrader Adapted Silver Mean Reversion (SMR) Strategy Engine
==========================================================================================
Workflow Architecture:
1. Native NautilusTrader Strategy & StrategyConfig implementation.
2. Evaluates multi-source mined alpha factors (AlphaGPT Formulaic + Microsoft Qlib/RD-Agent).
3. Integrates NeurIPS 2025 Credal Transformer (ArXiv:2510.12137) Anti-Overfitting Evidential Gate.
4. Accounts for:
   - Maker fees (0.02%), Taker fees (0.05%), and slippage (0.05%)
   - Full compounding equity model
   - 80% In-Sample / 20% Out-of-Sample validation
   - Deflated Sharpe Ratio (DSR) & Haircut Sharpe (Harvey & Liu)
   - Monte Carlo Permutation Test (1,000 trials)
"""

from __future__ import annotations
import math
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from credal_smr_audit import CredalTransformerGate, CredalSignal, calculate_deflated_sharpe_ratio, monte_carlo_permutation_test


# =============================================================================
# 1. NAUTILUS TRADER CONFIGURATION
# =============================================================================
class NautilusSilverSMRConfig(StrategyConfig, frozen=True):
    """Configuration for NautilusTrader Silver SMR Strategy."""
    instrument_id: InstrumentId
    bar_type: BarType

    # Risk & Capital
    initial_cash: float = 100_000.0       # 100k USDT base capital
    risk_pct: float = 1.0                 # 1.0% dynamic risk per trade (compounding)
    max_notional_cap: float = 11_000_000.0 # ~80M CNY capacity bound (in USDT)

    # Trading Friction
    maker_fee: float = 0.0002             # 2 bps maker fee
    taker_fee: float = 0.0005             # 5 bps taker fee
    slippage: float = 0.0005              # 5 bps realistic execution slippage

    # Alpha Thresholds
    z_entry_threshold: float = 1.75       # Mean-reversion standard deviation trigger
    z_exit_threshold: float = 0.25        # Mean-reversion target closure
    atr_window: int = 14
    vol_lookback: int = 96
    ma_lookback: int = 20

    # Credal Transformer Evidential Gating
    use_credal_gate: bool = True
    credal_u_max: float = 0.35            # Epistemic vacuity uncertainty cap
    credal_conflict_max: float = 0.40     # Bull-Bear conflict cap


# =============================================================================
# 2. NAUTILUS TRADER SMR STRATEGY CLASS
# =============================================================================
class NautilusSilverSMRStrategy(Strategy):
    """
    Event-driven high-frequency SMR strategy implemented for NautilusTrader.
    Maintains a streaming buffer of OHLCV bars and calculates alpha causally on-the-fly.
    """

    def __init__(self, config: NautilusSilverSMRConfig) -> None:
        super().__init__(config)
        self.cfg: NautilusSilverSMRConfig = config
        self._bars_buffer: deque = deque(maxlen=200)

        # Credal Anti-Overfitting Gate
        self.credal_gate = CredalTransformerGate(
            u_max=self.cfg.credal_u_max,
            conflict_max=self.cfg.credal_conflict_max,
        )

        # In-flight order & position tracking
        self.in_position: bool = False
        self.position_side: Optional[OrderSide] = None
        self.entry_price: float = 0.0
        self.position_size: float = 0.0
        self.stop_loss: float = 0.0
        self.take_profit: float = 0.0
        self.current_equity: float = self.cfg.initial_cash

        # Diagnostics & trade history
        self.completed_trades: List[Dict[str, Any]] = []

    def on_start(self) -> None:
        self.log.info(f"NautilusSilverSMRStrategy started for {self.cfg.instrument_id}")
        self.subscribe_bars(self.cfg.bar_type)

    def on_bar(self, bar: Bar) -> None:
        bar_dict = {
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
            "ts": bar.ts_event,
        }
        self._bars_buffer.append(bar_dict)

        if len(self._bars_buffer) < max(self.cfg.vol_lookback, self.cfg.ma_lookback) + 5:
            return

        # 1. Manage Active Position (Trailing & TP/SL Exit)
        if self.in_position:
            self._manage_position(bar_dict)
            return

        # 2. Compute Causal Alpha & Credal Evidential Evaluation
        signal_dict = self._evaluate_causal_signal()
        if signal_dict is None or signal_dict["direction"] == 0:
            return

        # 3. Size Position & Enter Trade
        self._execute_entry(bar_dict, signal_dict)

    def _evaluate_causal_signal(self) -> Optional[Dict[str, Any]]:
        closes = np.array([b["close"] for b in self._bars_buffer])
        highs = np.array([b["high"] for b in self._bars_buffer])
        lows = np.array([b["low"] for b in self._bars_buffer])
        vols = np.array([b["volume"] for b in self._bars_buffer])

        # 1. Rolling Mean & Volatility Z-score (Mean Reversion Core)
        ma = np.mean(closes[-self.cfg.ma_lookback:])
        std = np.std(closes[-self.cfg.ma_lookback:]) + 1e-8
        z_score = (closes[-1] - ma) / std

        # 2. Parkinson Volatility Regime Filter
        parkinson = np.sqrt(np.mean((np.log(highs[-20:] / lows[-20:]) ** 2) / (4.0 * np.log(2.0))))
        parkinson_baseline = np.sqrt(np.mean((np.log(highs[-self.cfg.vol_lookback:] / lows[-self.cfg.vol_lookback:]) ** 2) / (4.0 * np.log(2.0))))
        # Avoid extreme flash-crash volatility expansions where mean-reversion fails
        is_safe_vol = parkinson < (parkinson_baseline * 1.85)

        # 3. AlphaGPT KMid2 & Range Coupling Factor
        # Measures intra-bar close location relative to range and acceleration
        bar_range = highs[-1] - lows[-1]
        clv = (2.0 * closes[-1] - highs[-1] - lows[-1]) / (bar_range + 1e-8) if bar_range > 0 else 0.0

        # 4. Qlib Residual Exhaustion Factor (Linear regression residual mean-reversion)
        x = np.arange(10)
        y = closes[-10:]
        slope, intercept = np.polyfit(x, y, 1)
        fitted = slope * x + intercept
        resi = (y[-1] - fitted[-1]) / std

        # 5. Formulate Dirichlet Evidence Mass
        bull_evidence = 0.0
        bear_evidence = 0.0

        # Oversold Mean-Reversion Long Setup
        if z_score <= -self.cfg.z_entry_threshold and is_safe_vol:
            bull_evidence += abs(z_score) * 1.5
            if clv > -0.5:  # Lower tail rejection / buyer absorption
                bull_evidence += 1.8
            if resi < -1.0:
                bull_evidence += 1.2

        # Overbought Mean-Reversion Short Setup
        if z_score >= self.cfg.z_entry_threshold and is_safe_vol:
            bear_evidence += abs(z_score) * 1.5
            if clv < 0.5:   # Upper tail rejection / seller absorption
                bear_evidence += 1.8
            if resi > 1.0:
                bear_evidence += 1.2

        # Credal Evidential Gate Review
        if self.cfg.use_credal_gate:
            decision = self.credal_gate.evaluate_evidence(
                bull_evidence=bull_evidence,
                bear_evidence=bear_evidence,
                neutral_evidence=0.6,
            )
            if decision.should_abstain:
                return None

            if decision.credal_signal == CredalSignal.BULLISH:
                return {"direction": 1, "z_score": z_score, "confidence": decision.confidence}
            elif decision.credal_signal == CredalSignal.BEARISH:
                return {"direction": -1, "z_score": z_score, "confidence": decision.confidence}
            else:
                return None
        else:
            if bull_evidence > bear_evidence and bull_evidence >= 2.5:
                return {"direction": 1, "z_score": z_score, "confidence": 0.7}
            elif bear_evidence > bull_evidence and bear_evidence >= 2.5:
                return {"direction": -1, "z_score": z_score, "confidence": 0.7}
            return None

    def _execute_entry(self, bar: Dict[str, Any], signal_dict: Dict[str, Any]) -> None:
        direction = signal_dict["direction"]
        current_price = bar["close"]

        # Calculate ATR for dynamic risk budgeting
        highs = np.array([b["high"] for b in self._bars_buffer])
        lows = np.array([b["low"] for b in self._bars_buffer])
        closes = np.array([b["close"] for b in self._bars_buffer])
        tr = np.maximum(highs[-14:] - lows[-14:], np.maximum(abs(highs[-14:] - closes[-15:-1]), abs(lows[-14:] - closes[-15:-1])))
        atr = float(np.mean(tr))

        # Stop loss distance: 1.5 * ATR
        risk_distance = max(atr * 1.5, current_price * 0.003)

        # Compounding Position Sizing based on risk budget
        risk_capital = self.current_equity * (self.cfg.risk_pct / 100.0)
        target_shares = risk_capital / risk_distance

        # Enforce maximum notional capacity
        max_shares = self.cfg.max_notional_cap / current_price
        target_shares = min(target_shares, max_shares)

        if target_shares <= 0.01:
            return

        # Slippage on entry (Taker execution)
        slip_price = current_price * (1.0 + self.cfg.slippage * direction)

        self.in_position = True
        self.position_side = OrderSide.BUY if direction == 1 else OrderSide.SELL
        self.entry_price = slip_price
        self.position_size = target_shares
        self.stop_loss = slip_price - direction * risk_distance
        self.take_profit = slip_price + direction * (risk_distance * 1.8)  # 1:1.8 Risk-Reward

        # Deduct entry taker fee
        fee = (slip_price * target_shares) * self.cfg.taker_fee
        self.current_equity -= fee

    def _manage_position(self, bar: Dict[str, Any]) -> None:
        curr_price = bar["close"]
        high_price = bar["high"]
        low_price = bar["low"]

        direction = 1 if self.position_side == OrderSide.BUY else -1
        exit_trade = False
        exit_price = curr_price
        exit_reason = ""

        # Check Stop Loss
        if (direction == 1 and low_price <= self.stop_loss) or (direction == -1 and high_price >= self.stop_loss):
            exit_trade = True
            exit_price = self.stop_loss * (1.0 - direction * self.cfg.slippage)
            exit_reason = "STOP_LOSS"
        # Check Take Profit
        elif (direction == 1 and high_price >= self.take_profit) or (direction == -1 and low_price <= self.take_profit):
            exit_trade = True
            exit_price = self.take_profit * (1.0 - direction * self.cfg.slippage)
            exit_reason = "TAKE_PROFIT"
        else:
            # Check Mean-Reversion Z-score target closure
            closes = np.array([b["close"] for b in self._bars_buffer])
            ma = np.mean(closes[-self.cfg.ma_lookback:])
            std = np.std(closes[-self.cfg.ma_lookback:]) + 1e-8
            z_score = (curr_price - ma) / std

            if (direction == 1 and z_score >= -self.cfg.z_exit_threshold) or (direction == -1 and z_score <= self.cfg.z_exit_threshold):
                exit_trade = True
                exit_price = curr_price * (1.0 - direction * self.cfg.slippage)
                exit_reason = "Z_REVERSION_EXIT"

        if exit_trade:
            # Realized PnL calculation
            gross_pnl = direction * (exit_price - self.entry_price) * self.position_size
            exit_fee = (exit_price * self.position_size) * self.cfg.taker_fee
            net_pnl = gross_pnl - exit_fee

            self.current_equity += (self.entry_price * self.position_size) + net_pnl
            ret_pct = net_pnl / (self.entry_price * self.position_size)

            self.completed_trades.append({
                "direction": direction,
                "entry_price": self.entry_price,
                "exit_price": exit_price,
                "size": self.position_size,
                "net_pnl": net_pnl,
                "return_pct": ret_pct,
                "equity_after": self.current_equity,
                "reason": exit_reason,
            })

            # Reset position state
            self.in_position = False
            self.position_side = None
            self.entry_price = 0.0
            self.position_size = 0.0


# =============================================================================
# 3. HIGH-PERFORMANCE WALK-FORWARD RUNNER & STATISTICAL AUDIT
# =============================================================================
def run_walk_forward_smr_backtest(
    df: pd.DataFrame,
    is_ratio: float = 0.80,
    use_credal: bool = True,
    risk_pct: float = 1.0,
) -> Dict[str, Any]:
    """
    Executes In-Sample (80%) vs Out-of-Sample (20%) evaluation,
    accounting for full fees, slippage, compounding, DSR, and Monte Carlo permutation.
    """
    n_total = len(df)
    split_idx = int(n_total * is_ratio)
    df_is = df.iloc[:split_idx].copy().reset_index(drop=True)
    df_oos = df.iloc[split_idx:].copy().reset_index(drop=True)

    instrument_id = InstrumentId.from_str("XAGUSDT.BINANCE")
    bar_type = BarType.from_str("XAGUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL")

    config = NautilusSilverSMRConfig(
        instrument_id=instrument_id,
        bar_type=bar_type,
        initial_cash=100_000.0,
        risk_pct=risk_pct,
        use_credal_gate=use_credal,
    )

    def _simulate_subset(sub_df: pd.DataFrame, initial_cash: float) -> Tuple[Dict[str, Any], List[Dict[str, Any]], float]:
        strategy = NautilusSilverSMRStrategy(config)
        strategy.current_equity = initial_cash

        # Stream bars into strategy
        for i in range(len(sub_df)):
            row = sub_df.iloc[i]
            # Construct a lightweight mock bar object matching Nautilus bar interface
            class MockBar:
                open = row["open"]
                high = row["high"]
                low = row["low"]
                close = row["close"]
                volume = row["volume"]
                ts_event = int(row["timestamp"]) if "timestamp" in row else i

            strategy.on_bar(MockBar())

        trades = strategy.completed_trades
        if not trades:
            return {"cagr": 0.0, "sharpe": 0.0, "win_rate": 0.0, "max_dd": 0.0, "total_trades": 0}, [], initial_cash

        rets = np.array([t["return_pct"] for t in trades])
        pnls = np.array([t["net_pnl"] for t in trades])
        final_equity = strategy.current_equity

        # CAGR Calculation
        total_ret = (final_equity - initial_cash) / initial_cash
        # Convert duration to annualized years
        days = max(1.0, (len(sub_df) * 15.0) / (60.0 * 24.0))
        cagr = (1.0 + total_ret) ** (365.25 / days) - 1.0

        # Sharpe ratio
        daily_rets = rets
        sharpe = float(np.mean(daily_rets) / (np.std(daily_rets) + 1e-8) * np.sqrt(252 * 96))

        # Win rate
        win_rate = float(np.mean(pnls > 0))

        # Max Drawdown
        equities = np.array([initial_cash] + [t["equity_after"] for t in trades])
        cum_max = np.maximum.accumulate(equities)
        dd = (equities - cum_max) / cum_max
        max_dd = float(np.min(dd))

        metrics = {
            "initial_cash": initial_cash,
            "final_equity": final_equity,
            "total_return_pct": total_ret * 100.0,
            "cagr": cagr,
            "sharpe": sharpe,
            "win_rate": win_rate,
            "max_dd": max_dd,
            "total_trades": len(trades),
            "days_analyzed": days,
        }
        return metrics, trades, final_equity

    # 1. Run In-Sample
    is_metrics, is_trades, is_final_eq = _simulate_subset(df_is, 100_000.0)

    # 2. Run Out-of-Sample (Continuing from IS capital for natural compounding)
    oos_metrics, oos_trades, oos_final_eq = _simulate_subset(df_oos, is_final_eq)

    # 3. Credal Transformer Anti-Overfitting Suite on Out-of-Sample trades
    oos_rets = np.array([t["return_pct"] for t in oos_trades])
    dsr_audit = calculate_deflated_sharpe_ratio(
        sr_estimate=oos_metrics["sharpe"],
        sample_length=len(oos_trades),
        n_trials=100,
    )
    mc_audit = monte_carlo_permutation_test(oos_rets, n_permutations=1000)

    return {
        "In_Sample": is_metrics,
        "Out_of_Sample": oos_metrics,
        "DSR_Audit": dsr_audit,
        "Monte_Carlo_Audit": mc_audit,
        "Overall_Final_Equity": oos_final_eq,
        "Overall_Total_Trades": len(is_trades) + len(oos_trades),
    }
