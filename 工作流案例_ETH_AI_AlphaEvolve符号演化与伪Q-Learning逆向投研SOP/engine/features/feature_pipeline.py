"""
Strict No-Lookahead Bias Feature Engineering Pipeline
for 15-minute ETH perpetual contract K-lines.
Based on SPEC Section 6.1:
1. Log Returns: log(C_t / C_{t-1})
2. Normalized Volume: (Vol_t - SMA_20(Vol)) / Std_20(Vol)
3. Parkinson Volatility: High-Low Parkinson estimator over past 20 bars
4. Realized Volatility: rolling std of log returns over past 20 bars
5. Trend Momentum: MACD(12,26,9), RSI(14)
6. Mean Reversion: Bollinger %B, Rolling Z-Score ((C - SMA_20)/Std_20)
7. Microstructure Order Flow Imbalance (OFI Proxy): (2 * taker_buy - volume) / (volume + 1e-8)
All features strictly computed from historical bars (t-1 or inclusive past),
zero future leakage, zero bfill().
"""

import numpy as np
import pandas as pd
from numba import njit

@njit(fastmath=True)
def rolling_mean_1d(arr: np.ndarray, window: int) -> np.ndarray:
    n = len(arr)
    out = np.zeros(n, dtype=np.float64)
    if n < window:
        return out
    
    current_sum = 0.0
    for i in range(window):
        current_sum += arr[i]
        out[i] = current_sum / (i + 1)
        
    for i in range(window, n):
        current_sum += arr[i] - arr[i - window]
        out[i] = current_sum / window
    return out

@njit(fastmath=True)
def rolling_std_1d(arr: np.ndarray, window: int) -> np.ndarray:
    n = len(arr)
    out = np.zeros(n, dtype=np.float64)
    if n < window:
        return out
    
    for i in range(1, window):
        sub = arr[:i+1]
        out[i] = np.std(sub)
        
    for i in range(window, n):
        sub = arr[i - window + 1 : i + 1]
        out[i] = np.std(sub)
    return out

@njit(fastmath=True)
def calc_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    rsi = np.zeros(n, dtype=np.float64)
    if n <= period:
        return rsi
    
    gains = np.zeros(n, dtype=np.float64)
    losses = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        delta = close[i] - close[i - 1]
        if delta > 0:
            gains[i] = delta
        else:
            losses[i] = -delta
            
    avg_gain = np.mean(gains[1:period+1])
    avg_loss = np.mean(losses[1:period+1])
    
    if avg_loss == 0.0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - (100.0 / (1.0 + rs))
        
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0.0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))
            
    return rsi

@njit(fastmath=True)
def calc_parkinson_vol(high: np.ndarray, low: np.ndarray, window: int = 20) -> np.ndarray:
    n = len(high)
    out = np.zeros(n, dtype=np.float64)
    factor = 1.0 / (4.0 * np.log(2.0))
    log_hl_sq = np.zeros(n, dtype=np.float64)
    for i in range(n):
        ratio = high[i] / (low[i] + 1e-8)
        log_r = np.log(ratio)
        log_hl_sq[i] = log_r * log_r
        
    for i in range(window, n):
        sum_sq = 0.0
        for j in range(i - window + 1, i + 1):
            sum_sq += log_hl_sq[j]
        out[i] = np.sqrt(factor * (sum_sq / window))
    return out

class FeaturePipeline:
    def __init__(self, window_norm: int = 20):
        self.window_norm = window_norm

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Transforms raw OHLCV DataFrame into governed factor matrix.
        Input dataframe must have: ['open', 'high', 'low', 'close', 'volume']
        Optional: ['taker_buy_volume']
        """
        feats = pd.DataFrame(index=df.index)
        
        close = df['close'].values.astype(np.float64)
        high = df['high'].values.astype(np.float64)
        low = df['low'].values.astype(np.float64)
        volume = df['volume'].values.astype(np.float64)
        
        # 1. Log return
        ret = np.zeros_like(close)
        ret[1:] = np.log(close[1:] / (close[:-1] + 1e-8))
        feats['log_return'] = ret
        
        # 2. Normalized Volume
        vol_mean = rolling_mean_1d(volume, self.window_norm)
        vol_std = rolling_std_1d(volume, self.window_norm)
        safe_vol_std = np.where(vol_std > 1e-6, vol_std, 1.0)
        feats['norm_volume'] = np.where(vol_std > 1e-6, (volume - vol_mean) / safe_vol_std, 0.0)
        
        # 3. Parkinson Volatility & Realized Volatility
        feats['parkinson_vol'] = calc_parkinson_vol(high, low, self.window_norm)
        ret_std = rolling_std_1d(ret, self.window_norm)
        feats['realized_vol'] = ret_std
        
        # 4. Trend Momentum: MACD(12, 26, 9)
        ema12 = pd.Series(close).ewm(span=12, adjust=False).mean().values
        ema26 = pd.Series(close).ewm(span=26, adjust=False).mean().values
        dif = ema12 - ema26
        dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
        macd = 2.0 * (dif - dea)
        feats['macd_dif'] = dif
        feats['macd_hist'] = macd
        
        # 5. Trend Momentum: RSI(14)
        feats['rsi_14'] = (calc_rsi(close, 14) - 50.0) / 50.0  # Normalized to [-1, 1]
        
        # 6. Mean Reversion: Rolling Z-Score & Bollinger %B
        c_mean = rolling_mean_1d(close, self.window_norm)
        c_std = rolling_std_1d(close, self.window_norm)
        safe_c_std = np.where(c_std > 1e-6, c_std, 1.0)
        feats['z_score'] = np.where(c_std > 1e-6, (close - c_mean) / safe_c_std, 0.0)
        
        upper_b = c_mean + 2.0 * c_std
        lower_b = c_mean - 2.0 * c_std
        bb_width = upper_b - lower_b
        safe_bb_width = np.where(bb_width > 1e-6, bb_width, 1.0)
        feats['bollinger_b'] = np.where(bb_width > 1e-6, (close - lower_b) / safe_bb_width, 0.5)
        
        # 7. Microstructure OFI Proxy
        if 'taker_buy_volume' in df.columns:
            taker_vol = df['taker_buy_volume'].values.astype(np.float64)
            feats['ofi_proxy'] = np.where(volume > 1e-6, (2.0 * taker_vol - volume) / volume, 0.0)
        else:
            # Fallback estimation using High/Low/Close relative location
            hl_range = high - low
            feats['ofi_proxy'] = np.where(hl_range > 1e-6, (2.0 * (close - low) - hl_range) / hl_range, 0.0)
            
        # Replace any residual NaNs with 0.0 (strictly forward/zero, never bfill)
        feats.fillna(0.0, inplace=True)
        return feats
