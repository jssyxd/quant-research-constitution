"""
Multi-Asset 1-Minute and Multi-Timeframe High-Precision Data Loader & Lake Auditor.
Assets:
- BTC (BTCUSD.CRYPTO / Binance)
- GOLD (GLD.US_EQUITY / XAU)
- SILVER (SLV.US_EQUITY / XAG)
- NQ (E-mini Nasdaq-100 Futures / QQQ proxy)
- ES (E-mini S&P 500 Futures / SPY proxy)

Supports extracting 1m base bars from W:/database and generating aligned 15m, 1h, 2h, 3h, 4h bars,
retaining the raw 1m intraday slices for high-fidelity intra-bar matching!
"""

import os
from pathlib import Path
from typing import Dict, Tuple, Optional
import pandas as pd
import numpy as np

DATABANK_BAR_ROOT = Path("W:/database/03_governed_lake/nautilus_databank/catalog/data/bar")
RAW_LAKE_ROOT = Path("W:/database/01_raw_lake")
LOCAL_DATA_DIR = Path("010_btc_15m_moneyflow/data")

def load_governed_1m_parquet(folder_name: str, start_year: int = 2023, end_year: int = 2025) -> pd.DataFrame:
    """Load governed 1m catalog data across years."""
    folder_path = DATABANK_BAR_ROOT / folder_name
    if not folder_path.exists():
        raise FileNotFoundError(f"Directory {folder_path} does not exist")
    
    dfs = []
    for y in range(start_year, end_year + 1):
        f = folder_path / f"{y}.parquet"
        if f.exists():
            df_y = pd.read_parquet(f, columns=["timestamp", "open", "high", "low", "close", "volume"])
            dfs.append(df_y)
    
    if not dfs:
        # Check any parquet in folder
        for f in folder_path.glob("*.parquet"):
            df_y = pd.read_parquet(f, columns=["timestamp", "open", "high", "low", "close", "volume"])
            dfs.append(df_y)
            
    if not dfs:
        raise ValueError(f"No parquet data found in {folder_path}")
        
    df = pd.concat(dfs, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df

def load_asset_1m_data(symbol: str) -> pd.DataFrame:
    """
    Load raw 1-minute OHLCV data for given asset.
    Handles asset routing and data governance.
    """
    sym = symbol.upper()
    print(f"Loading 1m data for {sym}...")
    
    if sym == "BTC":
        return load_governed_1m_parquet("BTCUSD.CRYPTO-1-MINUTE-LAST-EXTERNAL", 2023, 2025)
    
    elif sym in ["GOLD", "GLD", "XAU"]:
        return load_governed_1m_parquet("GLD.US_EQUITY-1-MINUTE-LAST-EXTERNAL", 2023, 2025)
        
    elif sym in ["SILVER", "SLV", "XAG"]:
        return load_governed_1m_parquet("SLV.US_EQUITY-1-MINUTE-LAST-EXTERNAL", 2023, 2025)
        
    elif sym == "ES":
        # Check 1m raw futures data
        p_raw = RAW_LAKE_ROOT / "github/getdata-finance/es-1m-ohlcv-stocks-historical-data/ES_1m.csv"
        if p_raw.exists():
            df = pd.read_csv(p_raw)
            df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
            df = df.set_index("datetime").sort_index()
            df = df[["open", "high", "low", "close", "volume"]]
            return df[~df.index.duplicated(keep="first")]
        else:
            # Fallback to SPY (1:1 S&P 500 ETF proxy)
            print("ES raw not found, loading SPY equity 1m as institutional proxy...")
            return load_governed_1m_parquet("SPY.US_EQUITY-1-MINUTE-LAST-EXTERNAL", 2023, 2025)
            
    elif sym == "NQ":
        # Check 1m raw futures data
        p_raw = RAW_LAKE_ROOT / "github/getdata-finance/nq-1m-ohlcv-stocks-historical-data/NQ_1m.csv"
        if p_raw.exists():
            df = pd.read_csv(p_raw)
            df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
            df = df.set_index("datetime").sort_index()
            df = df[["open", "high", "low", "close", "volume"]]
            return df[~df.index.duplicated(keep="first")]
        else:
            # Fallback to QQQ (1:1 Nasdaq-100 ETF proxy)
            print("NQ raw not found, loading QQQ equity 1m as institutional proxy...")
            return load_governed_1m_parquet("QQQ.US_EQUITY-1-MINUTE-LAST-EXTERNAL", 2023, 2025)
            
    raise ValueError(f"Unsupported symbol: {symbol}")

TIMEFRAME_RESAMPLE_MAP = {
    "15m": "15min",
    "1h": "1h",
    "2h": "2h",
    "3h": "3h",
    "4h": "4h",
}

def aggregate_timeframe_bars(df_1m: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample 1m bars to target timeframe bars: 15m, 1h, 2h, 3h, 4h.
    Standardized UTC alignment, strict bar open/high/low/close aggregation.
    """
    rule = TIMEFRAME_RESAMPLE_MAP.get(timeframe.lower())
    if not rule:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
        
    df_res = df_1m.resample(rule, closed='left', label='left').agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna()
    
    # Filter empty or zero-volume ghost bars if any
    df_res = df_res[df_res["volume"] > 0]
    return df_res
