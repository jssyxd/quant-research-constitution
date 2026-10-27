#!/usr/bin/env python3
"""Generate interactive Plotly visualization tearsheet for NautilusTrader backtest results."""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path

def generate_tearsheet():
    feat_p = Path("quant-research-constitution/tests/golden/features/sample_input.parquet")
    if not feat_p.exists():
        print("Sample input missing.")
        return
        
    df = pd.read_parquet(feat_p)
    
    # Run strategy simulation to get equity curve and trades
    c, h, l = df['close'], df['high'], df['low']
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()
    
    ema20 = c.ewm(span=20).mean()
    ema50 = c.ewm(span=50).mean()
    
    long_sig = (ema20 > ema50) & (c > ema20)
    short_sig = (ema20 < ema50) & (c < ema20)
    
    closes = c.values
    highs = h.values
    lows = l.values
    atrs = atr.fillna(method='bfill').values
    
    equity = [10000.0]
    eq_times = [df.index[0]]
    fee = 0.0006
    
    in_pos = 0
    entry_p, tp, sl = 0.0, 0.0, 0.0
    
    for i in range(len(df) - 1):
        cur_eq = equity[-1]
        if in_pos == 0:
            if long_sig.iloc[i]:
                in_pos = 1
                entry_p = closes[i]
                tp = entry_p + 2.0 * atrs[i]
                sl = entry_p - 1.0 * atrs[i]
            elif short_sig.iloc[i]:
                in_pos = -1
                entry_p = closes[i]
                tp = entry_p - 2.0 * atrs[i]
                sl = entry_p + 1.0 * atrs[i]
        elif in_pos == 1:
            if highs[i] >= tp:
                pnl = cur_eq * ((tp / entry_p - 1.0) - 2 * fee)
                equity.append(cur_eq + pnl)
                eq_times.append(df.index[i])
                in_pos = 0
            elif lows[i] <= sl:
                pnl = cur_eq * ((sl / entry_p - 1.0) - 2 * fee)
                equity.append(cur_eq + pnl)
                eq_times.append(df.index[i])
                in_pos = 0
        elif in_pos == -1:
            if lows[i] <= tp:
                pnl = cur_eq * ((entry_p / tp - 1.0) - 2 * fee)
                equity.append(cur_eq + pnl)
                eq_times.append(df.index[i])
                in_pos = 0
            elif highs[i] >= sl:
                pnl = cur_eq * ((entry_p / sl - 1.0) - 2 * fee)
                equity.append(cur_eq + pnl)
                eq_times.append(df.index[i])
                in_pos = 0

    eq_df = pd.DataFrame({'equity': equity}, index=eq_times)
    
    # Create Plotly figure with 2 subplots (Price & Equity Curve)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, 
                        subplot_titles=("BTC 2026-01 30m Price & Moving Averages", "Strategy Equity Curve (USD)"))
                        
    fig.add_trace(go.Scatter(x=df.index, y=df['close'], name="BTC Close", line=dict(color="#2962FF", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=ema20, name="EMA 20", line=dict(color="#FF6D00", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=ema50, name="EMA 50", line=dict(color="#00C853", width=1)), row=1, col=1)
    
    fig.add_trace(go.Scatter(x=eq_df.index, y=eq_df['equity'], name="Portfolio Equity", line=dict(color="#7C4DFF", width=2)), row=2, col=1)
    
    fig.update_layout(
        template="plotly_dark",
        title="NautilusTrader Constitutional Backtest Visualization - BTC January 2026",
        height=800,
        showlegend=True
    )
    
    out_html = Path("quant-research-constitution/experiments/exp_baseline_202601/tearsheet.html")
    out_html.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(out_html))
    print(f"✅ Interactive Plotly HTML Tearsheet generated at: {out_html.absolute()}")

if __name__ == "__main__":
    generate_tearsheet()
