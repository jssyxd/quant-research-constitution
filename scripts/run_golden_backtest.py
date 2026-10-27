#!/usr/bin/env python3
"""Golden Backtest Execution & Verification Script."""
import json
import pandas as pd
import numpy as np
from pathlib import Path

GOLDEN_DIR = Path("quant-research-constitution/tests/golden/backtest")
FEAT_DIR = Path("quant-research-constitution/tests/golden/features")

def run_backtest():
    input_path = FEAT_DIR / "sample_input.parquet"
    df = pd.read_parquet(input_path)
    
    # Simple strategy logic
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
    
    trades = 0
    wins = 0
    pnl_accum = 0.0
    in_pos = 0
    entry_p, tp, sl = 0.0, 0.0, 0.0
    fee = 0.0006
    
    for i in range(len(df) - 1):
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
                trades += 1
                wins += 1
                pnl_accum += (tp / entry_p - 1.0) - 2 * fee
                in_pos = 0
            elif lows[i] <= sl:
                trades += 1
                pnl_accum += (sl / entry_p - 1.0) - 2 * fee
                in_pos = 0
        elif in_pos == -1:
            if lows[i] <= tp:
                trades += 1
                wins += 1
                pnl_accum += (entry_p / tp - 1.0) - 2 * fee
                in_pos = 0
            elif highs[i] >= sl:
                trades += 1
                pnl_accum += (entry_p / sl - 1.0) - 2 * fee
                in_pos = 0
                
    wr = (wins / trades) if trades > 0 else 0.0
    return {
        "total_trades": int(trades),
        "total_wins": int(wins),
        "win_rate": round(float(wr), 4),
        "cumulative_pnl_pct": round(float(pnl_accum * 100), 4)
    }

def main():
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    metrics_path = GOLDEN_DIR / "expected_metrics.json"
    
    actual = run_backtest()
    
    if not metrics_path.exists():
        metrics_path.write_text(json.dumps(actual, indent=2))
        print(f"✅ Generated baseline expected_metrics.json at {metrics_path}: {actual}")
        return
        
    expected = json.loads(metrics_path.read_text())
    
    if actual == expected:
        print(f"✅ Golden Backtest Test PASSED: {actual}")
    else:
        print(f"❌ Golden Backtest Test FAILED! Expected {expected}, got {actual}")
        exit(1)

if __name__ == "__main__":
    main()
