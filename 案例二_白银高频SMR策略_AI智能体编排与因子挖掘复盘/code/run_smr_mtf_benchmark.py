"""
run_smr_mtf_benchmark.py - Benchmark Execution & 4-Tier Stress Audit for Silver SMR MTF
========================================================================================
Implements:
0. Maker 0.02% / Taker 0.05% fees with leverage notional
1. 综合业绩基准指标 (100k USDT base, CAGR, Sharpe, Sortino, Calmar, Win Rate, Profit Factor)
2. 10,000-Trial Monte Carlo Permutation Test (95% & 99% MaxDD, Ruin Prob, Max Consecutive Losses)
3. Noise & Slippage Sensitivity (Gaussian noise +/- 0.15%, 3x slippage)
4. Walk-Forward Analysis (6-month IS + 2-month OOS, WFE metric)
"""

import math
import json
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple

DATA_15M = "/home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/XAGUSDT/15m/XAGUSDT_15m_consolidated.parquet"
DATA_1M = "/home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/XAGUSDT/1m/XAGUSDT_1m_consolidated.parquet"


def load_mtf_data():
    df_15m = pd.read_parquet(DATA_15M)
    df_1m = pd.read_parquet(DATA_1M)

    df_15m["dt"] = pd.to_datetime(df_15m["datetime"], utc=True)
    df_1m["dt"] = pd.to_datetime(df_1m["datetime"], utc=True)

    df_15m = df_15m.sort_values("dt").reset_index(drop=True)
    df_1m = df_1m.sort_values("dt").reset_index(drop=True)

    # 15m Indicators
    c15 = df_15m["close"].values
    ma20_15 = pd.Series(c15).rolling(20).mean().values
    std20_15 = pd.Series(c15).rolling(20).std().values + 1e-8
    z_15 = (c15 - ma20_15) / std20_15

    h15 = df_15m["high"].values
    l15 = df_15m["low"].values
    tr15 = np.maximum(h15 - l15, np.maximum(abs(h15 - np.roll(c15, 1)), abs(l15 - np.roll(c15, 1))))
    atr15 = pd.Series(tr15).rolling(14).mean().values

    # Parkinson Volatility Filter
    pv15 = np.sqrt((np.log(h15 / l15) ** 2) / (4.0 * np.log(2.0)))
    pv_ma15 = pd.Series(pv15).rolling(20).mean().values
    pv_base15 = pd.Series(pv15).rolling(96).mean().values
    is_safe_vol15 = pv_ma15 < (pv_base15 * 1.65)

    df_15m["z_15"] = z_15
    df_15m["ma_anchor_15"] = ma20_15
    df_15m["atr_15"] = atr15
    df_15m["is_safe_vol_15"] = is_safe_vol15

    # Merge 15m regime backward onto 1m bars
    cols_15m = ["dt", "z_15", "ma_anchor_15", "atr_15", "is_safe_vol_15"]
    merged = pd.merge_asof(
        df_1m.sort_values("dt"),
        df_15m[cols_15m].sort_values("dt"),
        on="dt",
        direction="backward",
    )
    return merged


def simulate_mtf_strategy(
    df: pd.DataFrame,
    initial_cash: float = 100_000.0,
    risk_pct: float = 1.0,           # 1.0% equity risk
    leverage: float = 3.0,
    maker_fee: float = 0.0002,
    taker_fee: float = 0.0005,
    slippage: float = 0.0005,
    price_noise_std: float = 0.0,     # For noise perturbation test
    slippage_mult: float = 1.0,
) -> Dict[str, Any]:
    effective_slippage = slippage * slippage_mult

    c = df["close"].values.copy()
    h = df["high"].values.copy()
    l = df["low"].values.copy()
    o = df["open"].values.copy()
    dts = df["dt"].values

    if price_noise_std > 0.0:
        rng = np.random.default_rng(42)
        noise = rng.normal(0.0, price_noise_std, len(c))
        c *= (1.0 + noise)
        h *= (1.0 + noise)
        l *= (1.0 + noise)
        o *= (1.0 + noise)

    z15 = df["z_15"].values
    anchor15 = df["ma_anchor_15"].values
    atr15 = df["atr_15"].values
    safe_vol = df["is_safe_vol_15"].values

    kmid2 = (c - o) / (h - l + 1e-12)
    klow = (np.minimum(o, c) - l) / (o + 1e-12)
    khigh = (h - np.maximum(o, c)) / (o + 1e-12)

    equity = initial_cash
    equity_curve = [equity]
    trades = []
    trade_logs = []

    in_pos = False
    direction = 0
    entry_p = 0.0
    shares = 0.0
    sl = 0.0
    tp = 0.0
    entry_idx = 0
    be_active = False
    initial_risk_dist = 0.0

    consecutive_losses = 0
    max_consecutive_losses = 0

    for i in range(100, len(df)):
        curr_c = c[i]
        curr_h = h[i]
        curr_l = l[i]

        if in_pos:
            unrealized_r = direction * (curr_c - entry_p) / (initial_risk_dist + 1e-8)

            # Early Breakeven (0.75R)
            if not be_active and unrealized_r >= 0.75:
                be_active = True
                new_sl = entry_p + direction * (entry_p * 0.0005)
                if (direction == 1 and new_sl > sl) or (direction == -1 and new_sl < sl):
                    sl = new_sl

            exit_trade = False
            exit_p = curr_c
            reason = ""
            fee_rate = taker_fee

            # Stop Loss / Breakeven Hit
            if (direction == 1 and curr_l <= sl) or (direction == -1 and curr_h >= sl):
                exit_trade = True
                exit_p = sl * (1.0 - direction * effective_slippage)
                reason = "Rule: EARLY_BE_PROTECTION (0.75R hit, stop moved to entry+buffer)" if be_active else "Rule: HARD_STOP_LOSS (1.5x ATR breach)"
            # Take Profit Target Hit (1.8R)
            elif (direction == 1 and curr_h >= tp) or (direction == -1 and curr_l <= tp):
                exit_trade = True
                exit_p = tp * (1.0 - direction * effective_slippage)
                fee_rate = maker_fee
                reason = "Rule: TAKE_PROFIT_TARGET (1.8R limit reached)"
            # Macro Fair Value Anchor Hit
            elif (direction == 1 and curr_c >= anchor15[i] and unrealized_r >= 0.5) or \
                 (direction == -1 and curr_c <= anchor15[i] and unrealized_r >= 0.5):
                exit_trade = True
                exit_p = curr_c * (1.0 - direction * effective_slippage)
                reason = "Rule: MACRO_FAIR_VALUE_REVERSION (Price reverted to 15m MA anchor)"
            # Time-to-Live Expiry (120 1m bars = 2 hours max holding)
            elif (i - entry_idx) >= 120:
                exit_trade = True
                exit_p = curr_c * (1.0 - direction * effective_slippage)
                reason = "Rule: TIME_EXPIRY_TIMEOUT (2-hour holding horizon reached)"

            if exit_trade:
                gross_pnl = direction * (exit_p - entry_p) * shares
                exit_fee = (exit_p * shares) * fee_rate
                net_pnl = gross_pnl - exit_fee

                equity += net_pnl
                equity_curve.append(equity)

                if net_pnl > 0:
                    consecutive_losses = 0
                else:
                    consecutive_losses += 1
                    max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)

                trade_record = {
                    "trade_id": len(trades) + 1,
                    "entry_time": str(dts[entry_idx]),
                    "exit_time": str(dts[i]),
                    "direction": "LONG" if direction == 1 else "SHORT",
                    "entry_price": float(entry_p),
                    "exit_price": float(exit_p),
                    "shares": float(shares),
                    "notional": float(entry_p * shares),
                    "gross_pnl": float(gross_pnl),
                    "exit_fee": float(exit_fee),
                    "net_pnl": float(net_pnl),
                    "ret_pct": float(net_pnl / (entry_p * shares)),
                    "running_equity": float(equity),
                    "rule": reason,
                }
                trades.append(trade_record)
                trade_logs.append(trade_record)

                in_pos = False
                direction = 0
                shares = 0.0
                be_active = False

        else:
            if np.isnan(z15[i]) or not safe_vol[i]:
                continue

            # Long Setup: 15m oversold + 1m wick absorption
            long_cond = (z15[i] <= -1.80) and (klow[i] > khigh[i] * 1.30) and (kmid2[i] > -0.20)
            # Short Setup: 15m overbought + 1m upper wick rejection
            short_cond = (z15[i] >= 1.80) and (khigh[i] > klow[i] * 1.30) and (kmid2[i] < 0.20)

            target_dir = 1 if long_cond else (-1 if short_cond else 0)

            if target_dir != 0:
                risk_dist = max(atr15[i] * 1.5, curr_c * 0.004)
                risk_amt = equity * (risk_pct / 100.0)
                pos_shares = risk_amt / risk_dist

                # Cap notional by leverage
                max_shares = (equity * leverage) / curr_c
                pos_shares = min(pos_shares, max_shares)

                if pos_shares > 0.01:
                    slip_entry = curr_c * (1.0 + target_dir * effective_slippage * 0.5)
                    entry_fee = (slip_entry * pos_shares) * maker_fee

                    equity -= entry_fee
                    in_pos = True
                    direction = target_dir
                    entry_p = slip_entry
                    shares = pos_shares
                    sl = slip_entry - target_dir * risk_dist
                    tp = slip_entry + target_dir * (risk_dist * 1.80)
                    initial_risk_dist = risk_dist
                    entry_idx = i
                    be_active = False

    # Summary Metrics
    eq_arr = np.array(equity_curve)
    pnls = np.array([t["net_pnl"] for t in trades])
    rets = np.array([t["ret_pct"] for t in trades])

    total_trades = len(trades)
    winning_trades = np.sum(pnls > 0)
    losing_trades = np.sum(pnls <= 0)
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

    total_return_pct = (equity - initial_cash) / initial_cash * 100.0
    days = max(1.0, len(df) / 1440.0)
    cagr = ((1.0 + total_return_pct / 100.0) ** (365.25 / days) - 1.0) * 100.0 if total_return_pct > -99.0 else -100.0

    cum_max = np.maximum.accumulate(eq_arr)
    dd = (cum_max - eq_arr) / cum_max
    max_dd_pct = float(np.max(dd) * 100.0) if len(dd) > 0 else 0.0

    # Sharpe (annualized assuming 4-6 trades/day)
    sharpe = float(np.mean(rets) / (np.std(rets) + 1e-8) * np.sqrt(252 * 5)) if total_trades > 5 else 0.0

    # Sortino (downside risk only)
    downside_rets = rets[rets < 0]
    downside_std = np.std(downside_rets) if len(downside_rets) > 0 else 1e-8
    sortino = float(np.mean(rets) / (downside_std + 1e-8) * np.sqrt(252 * 5)) if total_trades > 5 else 0.0

    # Calmar (CAGR / MaxDD)
    calmar = float(cagr / max_dd_pct) if max_dd_pct > 0.01 else 0.0

    # Profit Factor
    gross_wins = np.sum(pnls[pnls > 0])
    gross_losses = abs(np.sum(pnls[pnls < 0]))
    profit_factor = float(gross_wins / gross_losses) if gross_losses > 0 else float("inf")

    avg_win = float(np.mean(pnls[pnls > 0])) if winning_trades > 0 else 0.0
    avg_loss = float(abs(np.mean(pnls[pnls < 0]))) if losing_trades > 0 else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")

    return {
        "initial_capital": initial_cash,
        "final_capital": equity,
        "total_return_pct": total_return_pct,
        "cagr_pct": cagr,
        "max_drawdown_pct": max_dd_pct,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
        "total_trades": total_trades,
        "winning_trades": int(winning_trades),
        "losing_trades": int(losing_trades),
        "win_rate_pct": win_rate * 100.0,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_loss_ratio": win_loss_ratio,
        "max_consecutive_losses": max_consecutive_losses,
        "trades": trades,
        "equity_curve": eq_arr.tolist(),
    }


def run_monte_carlo_10000(pnls: np.ndarray, initial_cash: float, risk_pct: float) -> Dict[str, Any]:
    """10,000-trial Monte Carlo simulation by shuffling trade sequence."""
    rng = np.random.default_rng(42)
    max_dds = []
    ruin_count = 0

    for _ in range(10000):
        shuffled = rng.permutation(pnls)
        eq = initial_cash + np.cumsum(shuffled)
        peak = np.maximum.accumulate(eq)
        dd = (peak - eq) / peak
        max_dds.append(np.max(dd))
        if np.min(eq) <= (initial_cash * 0.50):
            ruin_count += 1

    max_dds = np.array(max_dds) * 100.0
    p95_mdd = float(np.percentile(max_dds, 95))
    p99_mdd = float(np.percentile(max_dds, 99))
    ruin_prob = float(ruin_count / 10000.0 * 100.0)

    return {
        "mc_95_max_dd_pct": p95_mdd,
        "mc_99_max_dd_pct": p99_mdd,
        "risk_of_ruin_pct": ruin_prob,
    }


def run_walk_forward_6m_2m(df: pd.DataFrame) -> Dict[str, Any]:
    """6 months In-Sample (IS) + 2 months Out-of-Sample (OOS) Walk-Forward Analysis."""
    bars_per_day = 1440
    is_bars = 180 * bars_per_day   # 6 months
    oos_bars = 60 * bars_per_day   # 2 months

    total_bars = len(df)
    if total_bars < (is_bars + oos_bars):
        # Scale down proportionally if dataset is shorter
        ratio = total_bars / (is_bars + oos_bars)
        is_bars = int(is_bars * ratio * 0.75)
        oos_bars = int(total_bars - is_bars)

    df_is = df.iloc[:is_bars].reset_index(drop=True)
    df_oos = df.iloc[is_bars:is_bars + oos_bars].reset_index(drop=True)

    res_is = simulate_mtf_strategy(df_is, initial_cash=100_000.0)
    res_oos = simulate_mtf_strategy(df_oos, initial_cash=res_is["final_capital"])

    is_sr = res_is["sharpe_ratio"]
    oos_sr = res_oos["sharpe_ratio"]
    wfe = oos_sr / is_sr if is_sr > 0 else 0.0

    return {
        "is_sharpe": is_sr,
        "oos_sharpe": oos_sr,
        "wfe": wfe,
        "is_win_rate": res_is["win_rate_pct"],
        "oos_win_rate": res_oos["win_rate_pct"],
        "is_trades": res_is["total_trades"],
        "oos_trades": res_oos["total_trades"],
    }
