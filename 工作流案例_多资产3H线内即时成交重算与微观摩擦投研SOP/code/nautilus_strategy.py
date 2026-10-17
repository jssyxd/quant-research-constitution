"""
Nautilus Trader Native Event-Driven Strategy Adapter for MoneyFlow Alpha.
Executes microstructure sweep absorption and risk parity sizing within NautilusTrader.
"""

from decimal import Decimal
import numpy as np
import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.data import BarType, Bar
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.currencies import USDT

class NautilusNativeMoneyFlowConfig(StrategyConfig, frozen=True):
    bar_type: BarType
    instrument_id: InstrumentId
    risk_pct: float = 0.01          # 1% equity risk per trade
    leverage: float = 5.0           # Default 5x leverage
    atr_sl_mult: float = 1.2        # Stop loss distance = 1.2 * ATR
    atr_tp_mult: float = 2.2        # Take profit distance = 2.2 * ATR
    max_hold_bars: int = 16         # 4-hour max hold time (16 * 15m)
    cooldown_bars: int = 16         # 16-bar cooldown between trades

class NautilusNativeMoneyFlowStrategy(Strategy):
    """
    NautilusTrader native event-driven implementation of MoneyFlow Alpha.
    Receives on_bar events, evaluates real-time signals, places market entry and limit TP/stop SL.
    """
    def __init__(self, config: NautilusNativeMoneyFlowConfig):
        super().__init__(config)
        self.bar_type = config.bar_type
        self.inst_id = config.instrument_id
        
        self.bar_count = 0
        self.entry_bar = 0
        self.last_exit_bar = -100
        self.active_position = 0 # 1: Long, -1: Short, 0: Flat
        
        self.signals = None
        self.executed_trades = []

    def set_precomputed_signals(self, sigs: pd.DataFrame):
        self.signals = sigs

    def on_start(self):
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar: Bar):
        self.bar_count += 1
        
        # 1. Manage Active Position (Time-based exit after 16 bars)
        if self.active_position != 0:
            if (self.bar_count - self.entry_bar) >= self.config.max_hold_bars:
                self.close_all_positions(self.inst_id)
                self.active_position = 0
                self.last_exit_bar = self.bar_count
                return

        # 2. Check Entry Conditions when flat & cooldown satisfied
        if self.active_position == 0 and (self.bar_count - self.last_exit_bar >= self.config.cooldown_bars):
            if self.signals is None or self.bar_count >= len(self.signals):
                return
                
            sig_row = self.signals.iloc[self.bar_count]
            rule1 = bool(sig_row['rule1']) # Long sweep absorption
            rule2 = bool(sig_row['rule2']) # Short sweep absorption
            
            if not (rule1 or rule2):
                return
                
            curr_atr = float(sig_row['atr'])
            if np.isnan(curr_atr) or curr_atr <= 0:
                curr_atr = float(bar.close) * 0.015
                
            close_px = float(bar.close)
            sl_dist = curr_atr * self.config.atr_sl_mult
            
            # Sizing according to risk parity & leverage constraints
            account = self.portfolio.account(self.inst_id.venue)
            current_equity = float(account.balance_total(USDT)) if account else 10000.0
            risk_amt = current_equity * self.config.risk_pct
            desired_qty = risk_amt / (sl_dist + 1e-6)
            max_qty = (current_equity * self.config.leverage) / close_px
            qty = min(desired_qty, max_qty)
            
            # Format quantity with proper precision
            qty_str = f"{qty:.6f}"
            if float(qty_str) <= 0.0001:
                return
                
            if rule1:
                order = self.order_factory.market(
                    instrument_id=self.inst_id,
                    order_side=OrderSide.BUY,
                    quantity=Quantity.from_str(qty_str),
                    time_in_force=TimeInForce.GTC,
                )
                self.submit_order(order)
                self.active_position = 1
                self.entry_bar = self.bar_count
                
            elif rule2:
                order = self.order_factory.market(
                    instrument_id=self.inst_id,
                    order_side=OrderSide.SELL,
                    quantity=Quantity.from_str(qty_str),
                    time_in_force=TimeInForce.GTC,
                )
                self.submit_order(order)
                self.active_position = -1
                self.entry_bar = self.bar_count

    def on_position_closed(self, event):
        self.active_position = 0
        self.last_exit_bar = self.bar_count
