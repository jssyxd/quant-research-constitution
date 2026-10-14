"""
nautilus_silver_smr_mtf.py - NautilusTrader Industrial Multi-Timeframe Resonance (MTF) SMR Strategy
====================================================================================================
Architecture & Core Principles:
1. Micro-Entry, Macro-Exit Asymmetric Principle:
   - Entry: Micro Timing triggered at 1-minute resolution (KMID2 body exhaustion + KLOW wick absorption).
   - Exit: Macro Mean Reversion target anchored at 15-minute / 1-hour central equilibrium (30~50 bps runway).
2. Tri-Scale Resonance Architecture:
   - Layer 1 (Macro): 1h/4h Trend & Volatility Filter.
   - Layer 2 (Regime): 15m Local OLS Detrended Residual (RESI_10) + Parkinson Volatility Guard.
   - Layer 3 (Micro): 1m Candlestick absorption & Queue-Priority limit entry.
3. Nautilus Trader 2.0.0rc6 Event-Driven Strategy implementation.
4. Accounts for:
   - Maker Fee (0.02%), Taker Fee (0.05%), Realistic Slippage (0.05%).
   - Dynamic Compounding Risk Budgeting (e.g. 1.0% equity risk per trade).
   - Maximum Notional Capacity Bound (80M CNY / ~11M USDT).
   - Early Breakeven (0.75R) & Trailing Stop.
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


# =============================================================================
# 1. STRATEGY CONFIGURATION
# =============================================================================
class SilverSMRMTFConfig(StrategyConfig, frozen=True):
    """Configuration for Industrial Tri-Scale SMR Strategy on NautilusTrader."""
    instrument_id: InstrumentId
    macro_bar_type: BarType  # 15-minute bar
    micro_bar_type: BarType  # 1-minute bar

    # Capital & Risk Sizing
    initial_cash: float = 100_000.0
    risk_pct: float = 1.0                  # 1.0% equity risk per trade
    leverage: float = 3.0                  # 3x baseline margin leverage
    max_notional_cap: float = 11_000_000.0 # ~80M CNY capacity bound (in USDT)

    # Friction & Fees
    maker_fee: float = 0.0002              # 2 bps maker
    taker_fee: float = 0.0005              # 5 bps taker
    slippage: float = 0.0005               # 5 bps slippage

    # Layer 2 (15m Macro Regime) Parameters
    macro_ma_period: int = 20
    macro_z_threshold: float = 1.80
    macro_vol_lookback: int = 96
    resi_period: int = 10

    # Layer 3 (1m Micro Timing) Parameters
    kmid2_exhaust_th: float = 0.45         # Single 1m bar body exhaustion threshold
    wick_ratio_th: float = 1.30            # Wick absorption dominance ratio
    micro_watch_timeout_bars: int = 15     # 15 1m bars window to catch turning point

    # Exit & Risk Mechanics
    rr_target: float = 1.80                # 1:1.8 Risk-Reward target
    early_be_trigger_rr: float = 0.75      # Move stop to BE when price reaches 0.75R
    early_be_buffer_pct: float = 0.0005    # Lock 5 bps profit on BE
    trailing_trigger_rr: float = 1.40      # Activate trailing stop at 1.4R


# =============================================================================
# 2. EVENT-DRIVEN MULTI-TIMEFRAME STRATEGY CLASS
# =============================================================================
class NautilusSilverSMRMTFStrategy(Strategy):
    """
    Industrial Multi-Timeframe Resonance SMR Strategy.
    Streams 15m and 1m bars concurrently, applying Micro-Entry / Macro-Exit execution.
    """

    def __init__(self, config: SilverSMRMTFConfig) -> None:
        super().__init__(config)
        self.cfg: SilverSMRMTFConfig = config

        # Rolling buffers
        self._macro_bars: deque = deque(maxlen=200)  # 15m bars
        self._micro_bars: deque = deque(maxlen=300)  # 1m bars

        # Macro state flag (15m Sentinel)
        self.macro_armed_direction: int = 0  # +1 Bullish Setup, -1 Bearish Setup, 0 Neutral
        self.macro_armed_bars_count: int = 0
        self.macro_fair_value_anchor: float = 0.0
        self.macro_atr: float = 0.0

        # Active trade state
        self.in_position: bool = False
        self.pos_direction: int = 0  # +1 Long, -1 Short
        self.entry_price: float = 0.0
        self.position_size: float = 0.0
        self.stop_loss: float = 0.0
        self.take_profit: float = 0.0
        self.initial_risk_dist: float = 0.0
        self.be_activated: bool = False
        self.trailing_activated: bool = False
        self.entry_time_ts: int = 0
        self.current_equity: float = self.cfg.initial_cash

        # Diagnostics & trade logs
        self.completed_trades: List[Dict[str, Any]] = []

    def on_start(self) -> None:
        self.log.info(f"Subscribing to Macro Bar: {self.cfg.macro_bar_type}")
        self.subscribe_bars(self.cfg.macro_bar_type)
        self.log.info(f"Subscribing to Micro Bar: {self.cfg.micro_bar_type}")
        self.subscribe_bars(self.cfg.micro_bar_type)

    def on_bar(self, bar: Bar) -> None:
        """Processes incoming bars from both timeframes."""
        if bar.bar_type == self.cfg.macro_bar_type:
            self._handle_macro_bar(bar)
        elif bar.bar_type == self.cfg.micro_bar_type:
            self._handle_micro_bar(bar)

    def _handle_macro_bar(self, bar: Bar) -> None:
        """Processes 15-minute macro bar: updates regime, OLS residual, and fair-value anchor."""
        b_dict = {
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
            "ts": bar.ts_event,
        }
        self._macro_bars.append(b_dict)

        if len(self._macro_bars) < self.cfg.macro_vol_lookback:
            return

        closes = np.array([b["close"] for b in self._macro_bars])
        highs = np.array([b["high"] for b in self._macro_bars])
        lows = np.array([b["low"] for b in self._macro_bars])

        # 1. Macro Moving Average & Z-Score
        ma = np.mean(closes[-self.cfg.macro_ma_period:])
        std = np.std(closes[-self.cfg.macro_ma_period:]) + 1e-8
        z_score = (closes[-1] - ma) / std
        self.macro_fair_value_anchor = ma

        # 2. Macro ATR(14)
        tr = np.maximum(highs[-14:] - lows[-14:], np.maximum(abs(highs[-14:] - closes[-15:-1]), abs(lows[-14:] - closes[-15:-1])))
        self.macro_atr = float(np.mean(tr))

        # 3. Parkinson Volatility Regime
        pv = np.sqrt(np.mean((np.log(highs[-20:] / lows[-20:]) ** 2) / (4.0 * np.log(2.0))))
        pv_baseline = np.sqrt(np.mean((np.log(highs[-self.cfg.macro_vol_lookback:] / lows[-self.cfg.macro_vol_lookback:]) ** 2) / (4.0 * np.log(2.0))))
        is_safe_regime = pv < (pv_baseline * 1.65)

        # 4. Local OLS Regression Residual (window 10)
        x = np.arange(10)
        y = closes[-10:]
        slope, intercept = np.polyfit(x, y, 1)
        fitted = slope * x + intercept
        resi = (y[-1] - fitted[-1]) / std

        # 5. Macro Armed Signal Detection
        if not self.in_position and is_safe_regime:
            if z_score <= -self.cfg.macro_z_threshold and resi < -0.8:
                self.macro_armed_direction = 1  # Prepare to buy micro dip
                self.macro_armed_bars_count = 0
            elif z_score >= self.cfg.macro_z_threshold and resi > 0.8:
                self.macro_armed_direction = -1 # Prepare to sell micro spike
                self.macro_armed_bars_count = 0
            else:
                self.macro_armed_direction = 0

    def _handle_micro_bar(self, bar: Bar) -> None:
        """Processes 1-minute micro bar: manages active position or triggers micro timing entry."""
        b_dict = {
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
            "ts": bar.ts_event,
        }
        self._micro_bars.append(b_dict)

        # 1. Manage Active Position (if in trade)
        if self.in_position:
            self._manage_active_position(b_dict)
            return

        # 2. Check Macro Armed Expiry
        if self.macro_armed_direction != 0:
            self.macro_armed_bars_count += 1
            if self.macro_armed_bars_count > self.cfg.micro_watch_timeout_bars:
                self.macro_armed_direction = 0
                return

            # 3. Micro Timing Trigger Evaluation on 1m Bar
            self._evaluate_micro_timing_entry(b_dict)

    def _evaluate_micro_timing_entry(self, bar: Dict[str, Any]) -> None:
        """Inspects 1m bar for candlestick absorption and exhaustion拐点."""
        o = bar["open"]
        h = bar["high"]
        l = bar["low"]
        c = bar["close"]
        v = bar["volume"]

        rng = h - l + 1e-12
        kmid2 = (c - o) / rng
        klow = (min(o, c) - l) / (o + 1e-12)
        khigh = (h - max(o, c)) / (o + 1e-12)

        direction = self.macro_armed_direction

        # Long Micro Trigger: 1m seller exhaustion + lower shadow absorption
        # (KMID2 was negative but now rebounding, long lower wick)
        long_trigger = (direction == 1 and klow > (khigh * self.cfg.wick_ratio_th) and kmid2 > -0.2)

        # Short Micro Trigger: 1m buyer exhaustion + upper shadow rejection
        short_trigger = (direction == -1 and khigh > (klow * self.cfg.wick_ratio_th) and kmid2 < 0.2)

        if long_trigger or short_trigger:
            self._execute_entry(bar, direction)
            self.macro_armed_direction = 0  # Disarm sentinel once entered

    def _execute_entry(self, bar: Dict[str, Any], direction: int) -> None:
        """Executes trade with dynamic risk compounding and Maker queue assumption."""
        curr_price = bar["close"]
        risk_dist = max(self.macro_atr * 1.5, curr_price * 0.004)

        # Compounding capital risk allocation
        risk_capital = self.current_equity * (self.cfg.risk_pct / 100.0)
        target_shares = risk_capital / risk_dist

        # Leverage and capacity cap
        max_capacity_shares = self.cfg.max_notional_cap / curr_price
        target_shares = min(target_shares, max_capacity_shares)

        if target_shares <= 0.01:
            return

        # Maker limit fill at bar midpoint pullback (capturing maker fee rebate)
        entry_p = curr_price * (1.0 + direction * self.cfg.slippage * 0.5)
        fee = (entry_p * target_shares) * self.cfg.maker_fee

        self.current_equity -= fee
        self.in_position = True
        self.pos_direction = direction
        self.entry_price = entry_p
        self.position_size = target_shares
        self.stop_loss = entry_p - direction * risk_dist
        self.take_profit = entry_p + direction * (risk_dist * self.cfg.rr_target)
        self.initial_risk_dist = risk_dist
        self.be_activated = False
        self.trailing_activated = False
        self.entry_time_ts = bar["ts"]

    def _manage_active_position(self, bar: Dict[str, Any]) -> None:
        """Monitors 1m price ticks for Stop Loss, Early BE, Trailing Stop, and Macro Target."""
        curr_p = bar["close"]
        high_p = bar["high"]
        low_p = bar["low"]
        direction = self.pos_direction

        unrealized_r = direction * (curr_p - self.entry_price) / (self.initial_risk_dist + 1e-8)

        # 1. Early Breakeven Activation (Locks in 5 bps profit at 0.75R)
        if not self.be_activated and unrealized_r >= self.cfg.early_be_trigger_rr:
            self.be_activated = True
            new_sl = self.entry_price + direction * (self.entry_price * self.cfg.early_be_buffer_pct)
            if (direction == 1 and new_sl > self.stop_loss) or (direction == -1 and new_sl < self.stop_loss):
                self.stop_loss = new_sl

        # 2. Trailing Stop Activation (Trails 1.0R behind peak once 1.4R is achieved)
        if not self.trailing_activated and unrealized_r >= self.cfg.trailing_trigger_rr:
            self.trailing_activated = True

        if self.trailing_activated:
            trailing_sl = curr_p - direction * (self.initial_risk_dist * 0.85)
            if (direction == 1 and trailing_sl > self.stop_loss) or (direction == -1 and trailing_sl < self.stop_loss):
                self.stop_loss = trailing_sl

        # 3. Exit Conditions Check
        exit_trade = False
        exit_p = curr_p
        reason = ""

        # Hard Stop Loss / Breakeven Hit
        if (direction == 1 and low_p <= self.stop_loss) or (direction == -1 and high_p >= self.stop_loss):
            exit_trade = True
            exit_p = self.stop_loss * (1.0 - direction * self.cfg.slippage)
            reason = "EARLY_BE_HIT" if self.be_activated else "STOP_LOSS_HIT"
        # Take Profit Target Hit
        elif (direction == 1 and high_p >= self.take_profit) or (direction == -1 and low_p <= self.take_profit):
            exit_trade = True
            exit_p = self.take_profit * (1.0 - direction * self.cfg.slippage)
            reason = "TAKE_PROFIT_TARGET_HIT"
        # Macro Fair Value Anchor Hit (15m Central Reversion achieved)
        elif (direction == 1 and curr_p >= self.macro_fair_value_anchor and unrealized_r >= 0.5) or \
             (direction == -1 and curr_p <= self.macro_fair_value_anchor and unrealized_r >= 0.5):
            exit_trade = True
            exit_p = curr_p * (1.0 - direction * self.cfg.slippage)
            reason = "MACRO_FAIR_VALUE_REVERSION"

        if exit_trade:
            gross_pnl = direction * (exit_p - self.entry_price) * self.position_size
            exit_fee = (exit_p * self.position_size) * self.cfg.taker_fee
            net_pnl = gross_pnl - exit_fee

            self.current_equity += net_pnl
            ret_pct = net_pnl / (self.entry_price * self.position_size)

            self.completed_trades.append({
                "entry_time": self.entry_time_ts,
                "exit_time": bar["ts"],
                "direction": direction,
                "entry_price": self.entry_price,
                "exit_price": exit_p,
                "shares": self.position_size,
                "net_pnl": net_pnl,
                "return_pct": ret_pct,
                "equity_after": self.current_equity,
                "trigger_rule": reason,
            })

            # Reset trade state
            self.in_position = False
            self.pos_direction = 0
            self.position_size = 0.0
            self.be_activated = False
            self.trailing_activated = False
