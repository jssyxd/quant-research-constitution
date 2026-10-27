#!/usr/bin/env python3
"""Golden feature computation & verification script."""
import pandas as pd
from pathlib import Path

GOLDEN_DIR = Path("quant-research-constitution/tests/golden/features")

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    res = df.copy()
    c, o, h, l, v = res['close'], res['open'], res['high'], res['low'], res['volume']
    
    # ATR 14
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    res['atr14'] = tr.ewm(span=14, adjust=False).mean()
    
    # OFI proxy
    hl_range = (h - l).replace(0, 1e-6)
    cl_v = ((2.0 * c - h - l) / hl_range) * v
    res['ofi'] = cl_v.rolling(window=8).mean() / (v.rolling(window=8).mean() + 1e-6)
    
    # CMF 16
    res['cmf'] = cl_v.rolling(16).sum() / (v.rolling(16).sum() + 1e-6)
    
    # Momentum Trend
    ema20 = c.ewm(span=20).mean()
    ema50 = c.ewm(span=50).mean()
    res['mom_trend'] = (ema20 - ema50) / (res['atr14'] + 1e-6)
    
    return res.dropna()

def main():
    input_path = GOLDEN_DIR / "sample_input.parquet"
    expected_path = GOLDEN_DIR / "expected_features.parquet"

    if not input_path.exists():
        print(f"Error: {input_path} missing.")
        exit(1)

    df = pd.read_parquet(input_path)
    actual = compute_features(df)

    if not expected_path.exists():
        expected_path.parent.mkdir(parents=True, exist_ok=True)
        actual.to_parquet(expected_path)
        print(f"✅ Generated baseline expected_features.parquet at {expected_path}")
        return

    expected = pd.read_parquet(expected_path)
    try:
        pd.testing.assert_frame_equal(actual, expected, rtol=1e-5, atol=1e-8)
        print("✅ Golden Feature Test PASSED: Output matches baseline perfectly.")
    except AssertionError as e:
        print("❌ Golden Feature Test FAILED: Drift detected!")
        print(e)
        actual.to_parquet(GOLDEN_DIR / "actual_failed.parquet")
        exit(1)

if __name__ == "__main__":
    main()
