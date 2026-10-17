"""
Jane Street Multi-Asset Multi-Timeframe Matrix Backtest Suite.
Executes 5 Assets x 5 Timeframes (25 Configurations):
- Assets: BTC, Gold (GLD), Silver (SLV), NQ, ES
- Timeframes: 15m, 1h, 2h, 3h, 4h
- Intra-Bar Execution with on_order_filled Recalculation & Collision-checking.
Outputs full quantitative evaluation matrix & JSON summaries.
"""

import sys
import json
import time
from pathlib import Path
import pandas as pd
import numpy as np

from multi_asset_loader import load_asset_1m_data, aggregate_timeframe_bars
from intrabar_engine import IntraBarMatrixEngine, EngineConfig

ASSETS = ["BTC", "GOLD", "SILVER", "NQ", "ES"]
TIMEFRAMES = ["15m", "1h", "2h", "3h", "4h"]

def run_matrix():
    print("=" * 90)
    print(" JANE STREET QUANTITATIVE RESEARCH - MULTI-ASSET INTRA-BAR MATRIX BACKTEST")
    print(" Strategy Rule: on_order_filled Intra-bar Recalculation with Risk-Parity Bracket")
    print(" Assets: BTC, GOLD (GLD), SILVER (SLV), NQ, ES | Timeframes: 15m, 1h, 2h, 3h, 4h")
    print(" Data Source: W:/database (03_governed_lake / 01_raw_lake)")
    print("=" * 90)

    matrix_results = []
    trade_logs = []
    
    start_all = time.time()

    for asset in ASSETS:
        print(f"\n>>> [ASSET START] Loading 1m Base Lake Data for {asset}...")
        t0 = time.time()
        try:
            df_1m = load_asset_1m_data(asset)
            print(f" -> {asset} loaded: {len(df_1m):,} 1m bars from {df_1m.index[0]} to {df_1m.index[-1]} ({time.time()-t0:.2f}s)")
        except Exception as e:
            print(f" -> ERROR loading {asset}: {e}")
            continue

        for tf in TIMEFRAMES:
            print(f"  -> Testing {asset:6} on {tf:3} ...", end="", flush=True)
            t_run = time.time()
            df_macro = aggregate_timeframe_bars(df_1m, tf)
            
            cfg = EngineConfig(
                symbol=asset,
                timeframe=tf,
                initial_capital=100000.0,
                risk_per_trade=0.01,
                max_leverage=3.0,
                limit_pullback_pct=0.002,
                atr_sl_mult=1.2,
                atr_tp_mult=2.4,
                max_hold_macro_bars=12,
                slippage_bps=3.0,
                fee_bps=3.0,
                pessimistic_collision=True
            )
            engine = IntraBarMatrixEngine(cfg)
            res = engine.run(df_1m, df_macro)
            
            # Save trade records
            trades = res.pop("trades", [])
            for t in trades:
                trade_logs.append({
                    "trade_id": t.trade_id,
                    "symbol": t.symbol,
                    "timeframe": t.timeframe,
                    "entry_time": str(t.entry_time),
                    "entry_price": t.entry_price,
                    "exit_time": str(t.exit_time),
                    "exit_price": t.exit_price,
                    "side": t.side,
                    "quantity": t.quantity,
                    "pnl": t.pnl,
                    "return_pct": t.return_pct,
                    "exit_reason": t.exit_reason,
                    "bars_held": t.bars_held
                })
                
            matrix_results.append(res)
            print(f" Done ({time.time()-t_run:.2f}s) | Trades: {res['total_trades']:<4} | Win: {res['win_rate']:>5.1f}% | Ret: {res['total_return_pct']:>7.1f}% | Sharpe: {res['sharpe_ratio']:>5.2f} | MaxDD: {res['max_drawdown_pct']:>5.2f}%")

    # Output directory
    out_dir = Path("010_btc_15m_moneyflow/reports/intrabar_matrix_run")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Save Matrix CSV
    df_matrix = pd.DataFrame(matrix_results)
    df_matrix.to_csv(out_dir / "intrabar_matrix_summary.csv", index=False)
    
    # 2. Save Trades CSV
    df_trades = pd.DataFrame(trade_logs)
    if not df_trades.empty:
        df_trades.to_csv(out_dir / "intrabar_matrix_trades.csv", index=False)

    print("\n" + "=" * 90)
    print(f" MATRIX RUN COMPLETED IN {time.time()-start_all:.1f}s")
    print(f" Output saved to: {out_dir}")
    print("=" * 90)
    
    # Print Pivoted View
    print("\n[Pivoted Cumulative Return %]")
    pivot_ret = df_matrix.pivot(index="symbol", columns="timeframe", values="total_return_pct")
    print(pivot_ret[TIMEFRAMES])
    
    print("\n[Pivoted Sharpe Ratio]")
    pivot_sharpe = df_matrix.pivot(index="symbol", columns="timeframe", values="sharpe_ratio")
    print(pivot_sharpe[TIMEFRAMES])

    print("\n[Pivoted Max Drawdown %]")
    pivot_dd = df_matrix.pivot(index="symbol", columns="timeframe", values="max_drawdown_pct")
    print(pivot_dd[TIMEFRAMES])

if __name__ == "__main__":
    run_matrix()
