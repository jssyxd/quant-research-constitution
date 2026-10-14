"""rd_qlib_miner_smr.py - Microsoft RD-Agent & Qlib Factor Mining for Silver Mean Reversion (SMR).

Executes hypothesis-driven alpha mining on pure OHLCV price/volume data of XAGUSDT
using Qlib Alpha158/Alpha360 primitives (KLOW, KHIGH, KMID, KMID2, WVMA, VSTD, ROC, BETA, RSQR, RESI, MAX, MIN, QTLU, QTLD).
"""

import sys
import json
from typing import Tuple, Dict
import numpy as np
import pandas as pd
from scipy import stats
from qlib.data.ops import rolling_slope, rolling_rsquare, rolling_resi

DATA_PATH_15M = '/home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/XAGUSDT/15m/XAGUSDT_15m_consolidated.parquet'
DATA_PATH_1M = '/home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/XAGUSDT/1m/XAGUSDT_1m_consolidated.parquet'


def load_data(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    return df


def compute_all_factors(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, pd.Series]]:
    """Compute all alpha factors and targets strictly using pure OHLCV data."""
    # Target Forward Returns (leak-free shift)
    df['ret_1'] = df['close'].shift(-1) / df['close'] - 1.0
    df['ret_2'] = df['close'].shift(-2) / df['close'] - 1.0
    df['ret_4'] = df['close'].shift(-4) / df['close'] - 1.0

    # Moving Average Benchmarks (reversion benchmark = -(close - MA) / MA)
    ma20 = df['close'].rolling(20).mean()
    bench_ma20 = -(df['close'] - ma20) / ma20
    ma60 = df['close'].rolling(60).mean()
    bench_ma60 = -(df['close'] - ma60) / ma60

    # 1. Candlestick Primitives
    # KMID = (close - open) / open
    kmid = (df['close'] - df['open']) / df['open']
    # KMID2 = (close - open) / (high - low + 1e-12)
    kmid2 = (df['close'] - df['open']) / (df['high'] - df['low'] + 1e-12)
    # KLOW = (min(open, close) - low) / open
    klow = (np.minimum(df['open'], df['close']) - df['low']) / df['open']
    # KHIGH = (high - max(open, close)) / open
    khigh = (df['high'] - np.maximum(df['open'], df['close'])) / df['open']
    # KSFT2 = (2 * close - high - low) / (high - low + 1e-12)
    ksft2 = (2.0 * df['close'] - df['high'] - df['low']) / (df['high'] - df['low'] + 1e-12)

    # 2. Rolling OLS Regression Primitives (window d=10, 20)
    close_vals = df['close'].values.astype(np.float64)
    resi_10 = pd.Series(rolling_resi(close_vals, 10), index=df.index) / df['close']
    resi_20 = pd.Series(rolling_resi(close_vals, 20), index=df.index) / df['close']
    rsqr_10 = pd.Series(rolling_rsquare(close_vals, 10), index=df.index)
    rsqr_20 = pd.Series(rolling_rsquare(close_vals, 20), index=df.index)
    beta_10 = pd.Series(rolling_slope(close_vals, 10), index=df.index) / df['close']
    beta_20 = pd.Series(rolling_slope(close_vals, 20), index=df.index) / df['close']

    # 3. Volatility & Volume Primitives
    ret_abs = (df['close'] / df['close'].shift(1) - 1.0).abs()
    pv_vol = ret_abs * df['volume']
    wvma_10 = pv_vol.rolling(10).std() / (pv_vol.rolling(10).mean() + 1e-12)
    wvma_20 = pv_vol.rolling(20).std() / (pv_vol.rolling(20).mean() + 1e-12)
    vstd_10 = df['volume'].rolling(10).std() / (df['volume'] + 1e-12)
    vstd_20 = df['volume'].rolling(20).std() / (df['volume'] + 1e-12)
    roc_10 = (df['close'] - df['close'].shift(10)) / df['close'].shift(10)
    roc_20 = (df['close'] - df['close'].shift(20)) / df['close'].shift(20)

    # 4. Extremum and Quantile Primitives
    max_10 = df['high'].rolling(10).max()
    min_10 = df['low'].rolling(10).min()
    q80_10 = df['close'].rolling(10).quantile(0.8)
    q20_10 = df['close'].rolling(10).quantile(0.2)
    q80_20 = df['close'].rolling(20).quantile(0.8)
    q20_20 = df['close'].rolling(20).quantile(0.2)

    # Dictionary of Defined Alpha Factors (Signed as positive alpha predicting positive return)
    factors = {
        # Generation 1: Candlestick Microstructure Dynamics
        'SMR_01_KMID2_REV': -kmid2,
        'SMR_02_CANDLE_EXHAUST': (klow - khigh) - kmid,
        'SMR_03_KSFT2_REV': -ksft2,

        # Generation 2: Detrended Regression & Linearity Dynamics
        'SMR_04_RESI_REV_10': -resi_10,
        'SMR_05_RSQR_RESI_EXHAUST_10': -(resi_10 * np.sqrt(rsqr_10.clip(0, 1) + 1e-6)),
        'SMR_06_RESI_REV_20': -resi_20,
        'SMR_07_ROC_BETA_DIV_10': -(roc_10 - beta_10 * 10),

        # Generation 3: Volatility & Volume-Dispersion Coupling
        'SMR_08_WVMA_KMID2_10': -kmid2 * wvma_10,
        'SMR_09_VSTD_KMID2_10': -kmid2 * (1.0 + vstd_10),
        'SMR_10_WVMA_RESI_10': -resi_10 * wvma_10,

        # Generation 4: Range Extremum & Quantile Elasticity
        'SMR_11_QTL_SQUEEZE_REV_10': -kmid2 / ((q80_10 - q20_10) / df['close'] + 1e-4),
        'SMR_12_BOUND_KMID2_COUPLING_10': ((max_10 - df['close']) - (df['close'] - min_10)) / df['close'] - 0.5 * kmid2,
    }

    # Standardize factors over rolling window (avoid lookahead) to form composites
    z_factors = pd.DataFrame(index=df.index)
    for col, s in factors.items():
        m = s.rolling(960, min_periods=96).mean()
        std = s.rolling(960, min_periods=96).std()
        z_factors[col] = (s - m) / (std + 1e-12)

    # Core 4-Factor Orthogonal Ensemble
    top4 = ['SMR_01_KMID2_REV', 'SMR_05_RSQR_RESI_EXHAUST_10', 'SMR_08_WVMA_KMID2_10', 'SMR_07_ROC_BETA_DIV_10']
    factors['SMR_COMPOSITE_CORE4'] = z_factors[top4].mean(axis=1)
    # Full Ensemble
    factors['SMR_COMPOSITE_FULL12'] = z_factors.mean(axis=1)

    return df, factors, bench_ma20, bench_ma60


def evaluate_factors(df: pd.DataFrame, factors: Dict[str, pd.Series], bench_ma20: pd.Series, bench_ma60: pd.Series):
    n_total = len(df)
    n_is = int(n_total * 0.8)
    
    summary = []
    for fname, fser in factors.items():
        row = {'factor': fname}
        for h_name, ret_col in [('15m', 'ret_1'), ('30m', 'ret_2'), ('1h', 'ret_4')]:
            # IS
            s_is = fser.iloc[:n_is]
            r_is = df[ret_col].iloc[:n_is]
            m_is = ~(s_is.isna() | r_is.isna() | np.isinf(s_is) | np.isinf(r_is))
            ric_is, _ = stats.spearmanr(s_is[m_is], r_is[m_is])
            
            # OOS
            s_oos = fser.iloc[n_is:]
            r_oos = df[ret_col].iloc[n_is:]
            b20_oos = bench_ma20.iloc[n_is:]
            b60_oos = bench_ma60.iloc[n_is:]
            m_oos = ~(s_oos.isna() | r_oos.isna() | np.isinf(s_oos) | np.isinf(r_oos) | b20_oos.isna())
            
            sc = s_oos[m_oos]
            rc = r_oos[m_oos]
            b20c = b20_oos[m_oos]
            b60c = b60_oos[m_oos]
            
            pic_oos, _ = stats.pearsonr(sc, rc)
            ric_oos, _ = stats.spearmanr(sc, rc)
            n_c = len(sc)
            t_oos = ric_oos * np.sqrt((n_c - 2) / (1.0 - ric_oos**2 + 1e-12))
            corr_b20, _ = stats.spearmanr(sc, b20c)
            corr_b60, _ = stats.spearmanr(sc, b60c)
            
            # Daily ICIR
            n_days = n_c // 96
            d_rics = []
            for i in range(n_days):
                sub_s = sc.iloc[i*96:(i+1)*96]
                sub_r = rc.iloc[i*96:(i+1)*96]
                if len(sub_s) >= 48:
                    d_r, _ = stats.spearmanr(sub_s, sub_r)
                    if not np.isnan(d_r):
                        d_rics.append(d_r)
            ic_mean = np.mean(d_rics) if len(d_rics) > 0 else ric_oos
            ic_std = np.std(d_rics) if len(d_rics) > 0 else 1.0
            icir = ic_mean / (ic_std + 1e-12)
            
            # Quintile spread (Q5 - Q1)
            try:
                q_ranks = pd.qcut(sc, 5, labels=False, duplicates='drop')
                q_rets = rc.groupby(q_ranks).mean()
                spread_bps = (q_rets.iloc[-1] - q_rets.iloc[0]) * 10000.0
            except:
                spread_bps = 0.0

            pass_test = (ric_oos > 0.030) and (t_oos > 2.5) and (abs(corr_b20) < 0.40)
            
            row[f'{h_name}_IS_RankIC'] = ric_is
            row[f'{h_name}_OOS_RankIC'] = ric_oos
            row[f'{h_name}_OOS_PearsonIC'] = pic_oos
            row[f'{h_name}_OOS_t'] = t_oos
            row[f'{h_name}_OOS_ICIR'] = icir
            row[f'{h_name}_Corr_MA20'] = corr_b20
            row[f'{h_name}_Corr_MA60'] = corr_b60
            row[f'{h_name}_Spread_bps'] = spread_bps
            row[f'{h_name}_Pass'] = pass_test
        summary.append(row)
    return pd.DataFrame(summary)


if __name__ == '__main__':
    print('Loading 15m XAGUSDT data...')
    from typing import Tuple, Dict
    df = load_data(DATA_PATH_15M)
    print(f'Total bars: {len(df)}, Date range: {df["datetime"].min()} to {df["datetime"].max()}')
    
    df, factors, bench_ma20, bench_ma60 = compute_all_factors(df)
    results_df = evaluate_factors(df, factors, bench_ma20, bench_ma60)
    
    print('\n================== 15m Forward Return Evaluation ==================')
    cols_15m = ['factor', '15m_IS_RankIC', '15m_OOS_RankIC', '15m_OOS_t', '15m_OOS_ICIR', '15m_Corr_MA20', '15m_Spread_bps', '15m_Pass']
    print(results_df[cols_15m].to_string(index=False))
