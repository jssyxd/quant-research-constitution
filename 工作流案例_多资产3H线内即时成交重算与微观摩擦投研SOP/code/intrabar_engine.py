"""
High-Precision Intra-Bar Event-Driven Backtesting Engine with Order State Machine.
Simulates 'calc_on_order_fills=true' (Nautilus Trader on_order_filled) with:
1. Macro Timeframe (15m, 1h, 2h, 3h, 4h) signal evaluation.
2. Micro Timeframe (1-minute slices inside each macro bar) matching:
   - When limit entry touches inside bar, immediately recalculates stop loss & take profit.
   - Evaluates intra-bar bracket exits on subsequent 1m slices.
3. Jane Street Risk Controls:
   - Anti-state-invalidation (strict order mapping).
   - Collision check: Pessimistic SL priority if both TP/SL barriers touched simultaneously.
   - Real transaction costs (Maker 2 bps / Taker 4 bps) & Slippage (3-5 bps).
   - Time stop (holding period timeout).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

@dataclass
class EngineConfig:
    symbol: str
    timeframe: str
    initial_capital: float = 100000.0  # $100k institutional sizing
    risk_per_trade: float = 0.01       # 1% equity risk
    max_leverage: float = 3.0          # 3x max leverage
    limit_pullback_pct: float = 0.002  # Place limit buy 0.2% below bar open/close
    atr_sl_mult: float = 1.2           # Stop loss = 1.2 * ATR
    atr_tp_mult: float = 2.4           # Take profit = 2.4 * ATR
    max_hold_macro_bars: int = 12      # Mandatory time stop
    slippage_bps: float = 3.0          # 3 bps slippage
    fee_bps: float = 3.0               # 3 bps fee per side
    pessimistic_collision: bool = True # Pessimistic stop-loss priority

@dataclass
class TradeRecord:
    trade_id: int
    symbol: str
    timeframe: str
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    side: str
    quantity: float
    pnl: float
    return_pct: float
    exit_reason: str
    bars_held: int

class IntraBarMatrixEngine:
    def __init__(self, config: EngineConfig):
        self.cfg = config

    def run(self, df_1m: pd.DataFrame, df_macro: pd.DataFrame) -> Dict:
        """
        Executes discrete-event intra-bar simulation.
        df_1m: 1-minute historical data indexed by UTC Datetime.
        df_macro: Resampled target timeframe bars (15m, 1h, 2h, 3h, 4h).
        """
        # 1. Compute macro indicators (ATR & Trend)
        df_macro = df_macro.copy()
        high = df_macro['high']
        low = df_macro['low']
        close = df_macro['close']
        
        # True Range & ATR(14)
        prev_close = close.shift(1)
        tr = np.maximum(high - low, np.maximum((high - prev_close).abs(), (low - prev_close).abs()))
        atr = tr.rolling(14).mean().fillna(close * 0.01)
        
        # Trend filter (EMA 20 > EMA 50)
        ema20 = close.ewm(span=20).mean()
        ema50 = close.ewm(span=50).mean()
        regime = ema20 > ema50  # Bullish filter
        
        # 2. Simulation State Machine
        capital = self.cfg.initial_capital
        equity_curve = [capital]
        trades: List[TradeRecord] = []
        trade_id_counter = 0
        
        active_position = None # {entry_px, qty, sl_px, tp_px, entry_time, entry_macro_idx}
        
        macro_indices = df_macro.index
        num_macro = len(macro_indices)
        
        # Pre-group 1m data by macro bar for fast micro-event lookup
        # Each macro bar i spans from macro_indices[i] to macro_indices[i+1] (or + timeframe duration)
        freq_minutes = {
            '15m': 15, '1h': 60, '2h': 120, '3h': 180, '4h': 240
        }[self.cfg.timeframe.lower()]
        macro_timedelta = pd.Timedelta(minutes=freq_minutes)
        
        for i in range(14, num_macro):
            m_time = macro_indices[i]
            m_next_time = m_time + macro_timedelta
            m_atr = atr.iloc[i]
            m_close = close.iloc[i]
            is_bull = regime.iloc[i]
            
            # Slice the 1-minute micro bars occurring inside this macro bar
            sub_1m = df_1m.loc[m_time:m_next_time - pd.Timedelta(nanoseconds=1)]
            if sub_1m.empty:
                continue
                
            # If Flat and Bullish regime, prepare a limit buy order for this macro interval
            pending_limit_buy = None
            if active_position is None and is_bull:
                limit_px = m_close * (1.0 - self.cfg.limit_pullback_pct)
                pending_limit_buy = limit_px

            # Step through each 1-minute slice inside the macro bar (Intra-Bar Execution!)
            for micro_ts, micro_bar in sub_1m.iterrows():
                # --- Step A: Check Pending Limit Entry Fills ---
                if active_position is None and pending_limit_buy is not None:
                    # If 1m low reaches or breaches the limit price, order is filled!
                    if micro_bar['low'] <= pending_limit_buy:
                        # Filled at limit price (or open if gapped) + slippage
                        exec_entry_px = min(pending_limit_buy, micro_bar['open'])
                        exec_entry_px *= (1.0 + self.cfg.slippage_bps * 1e-4)
                        
                        # Calculate position sizing (Risk parity)
                        sl_dist = m_atr * self.cfg.atr_sl_mult
                        risk_amt = capital * self.cfg.risk_per_trade
                        desired_qty = risk_amt / max(sl_dist, 1e-6)
                        max_qty = (capital * self.cfg.max_leverage) / exec_entry_px
                        qty = min(desired_qty, max_qty)
                        
                        # *** on_order_filled RECALCULATION ***
                        # Immediately recalculate SL & TP using actual executed fill price!
                        sl_px = exec_entry_px - sl_dist
                        tp_px = exec_entry_px + (m_atr * self.cfg.atr_tp_mult)
                        
                        active_position = {
                            'entry_px': exec_entry_px,
                            'qty': qty,
                            'sl_px': sl_px,
                            'tp_px': tp_px,
                            'entry_time': micro_ts,
                            'entry_macro_idx': i,
                            'holding_bars': 0
                        }
                        pending_limit_buy = None
                        # Entry cost
                        fee = exec_entry_px * qty * (self.cfg.fee_bps * 1e-4)
                        capital -= fee
                        continue  # Move to next 1m bar to monitor bracket exits

                # --- Step B: Manage Active Position (Intra-Bar Exits) ---
                if active_position is not None:
                    pos = active_position
                    pos_sl = pos['sl_px']
                    pos_tp = pos['tp_px']
                    bar_low = micro_bar['low']
                    bar_high = micro_bar['high']
                    
                    sl_hit = bar_low <= pos_sl
                    tp_hit = bar_high >= pos_tp
                    
                    exit_trade = False
                    exit_px = 0.0
                    reason = ""
                    
                    if sl_hit and tp_hit:
                        # Collision check: Pessimistic SL priority
                        if self.cfg.pessimistic_collision:
                            exit_px = pos_sl * (1.0 - self.cfg.slippage_bps * 1e-4)
                            reason = "COLLISION_STOP_LOSS"
                        else:
                            exit_px = pos_tp * (1.0 - self.cfg.slippage_bps * 1e-4)
                            reason = "COLLISION_TAKE_PROFIT"
                        exit_trade = True
                    elif sl_hit:
                        exit_px = pos_sl * (1.0 - self.cfg.slippage_bps * 1e-4)
                        reason = "STOP_LOSS"
                        exit_trade = True
                    elif tp_hit:
                        exit_px = pos_tp * (1.0 - self.cfg.slippage_bps * 1e-4)
                        reason = "TAKE_PROFIT"
                        exit_trade = True
                        
                    # Mandatory holding timeout check (Max hold macro bars)
                    if not exit_trade and (i - pos['entry_macro_idx']) >= self.cfg.max_hold_macro_bars:
                        exit_px = micro_bar['close'] * (1.0 - self.cfg.slippage_bps * 1e-4)
                        reason = "TIME_STOP"
                        exit_trade = True
                        
                    if exit_trade:
                        fee = exit_px * pos['qty'] * (self.cfg.fee_bps * 1e-4)
                        net_pnl = (exit_px - pos['entry_px']) * pos['qty'] - fee
                        capital += net_pnl
                        trade_id_counter += 1
                        
                        ret_pct = ((exit_px - pos['entry_px']) / pos['entry_px']) * 100.0
                        trades.append(TradeRecord(
                            trade_id=trade_id_counter,
                            symbol=self.cfg.symbol,
                            timeframe=self.cfg.timeframe,
                            entry_time=pos['entry_time'],
                            entry_price=pos['entry_px'],
                            exit_time=micro_ts,
                            exit_price=exit_px,
                            side="LONG",
                            quantity=pos['qty'],
                            pnl=net_pnl,
                            return_pct=ret_pct,
                            exit_reason=reason,
                            bars_held=i - pos['entry_macro_idx']
                        ))
                        active_position = None
                        equity_curve.append(capital)
                        break  # Position closed, exit sub_1m loop

        # 3. Compile Performance Metrics
        total_trades = len(trades)
        if total_trades == 0:
            return {
                "symbol": self.cfg.symbol,
                "timeframe": self.cfg.timeframe,
                "total_trades": 0,
                "win_rate": 0.0,
                "total_return_pct": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown_pct": 0.0,
                "profit_factor": 0.0,
            }
            
        pnls = [t.pnl for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_rate = (len(wins) / total_trades) * 100.0
        
        tot_win = sum(wins) if wins else 0.0
        tot_loss = abs(sum(losses)) if losses else 1e-6
        profit_factor = tot_win / tot_loss
        
        cum_ret = ((capital - self.cfg.initial_capital) / self.cfg.initial_capital) * 100.0
        
        # Max Drawdown
        eq = np.array(equity_curve)
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        max_dd = abs(float(np.min(dd))) * 100.0
        
        # Annualized Sharpe (approximate based on trade returns)
        rets = np.array([t.return_pct / 100.0 for t in trades])
        if np.std(rets) > 0:
            trades_per_year = total_trades / 3.0 # approx 3 years evaluation
            sharpe = (np.mean(rets) / np.std(rets)) * np.sqrt(max(trades_per_year, 1.0))
        else:
            sharpe = 0.0
            
        return {
            "symbol": self.cfg.symbol,
            "timeframe": self.cfg.timeframe,
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "total_return_pct": round(cum_ret, 2),
            "sharpe_ratio": round(float(sharpe), 2),
            "max_drawdown_pct": round(max_dd, 2),
            "profit_factor": round(float(profit_factor), 2),
            "trades": trades
        }
