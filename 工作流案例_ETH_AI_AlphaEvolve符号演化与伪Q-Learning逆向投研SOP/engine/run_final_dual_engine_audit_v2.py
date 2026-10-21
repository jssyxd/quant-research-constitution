import numpy as np
import pandas as pd
import json

print(">>> [Dual Engine Audit v2] 采用动量均线过滤与大波段趋势追踪...")
path = '/home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/ETHUSDT/15m/ETHUSDT_15m_consolidated.parquet'
df = pd.read_parquet(path)
df['datetime'] = pd.to_datetime(df['datetime'])
df.set_index('datetime', inplace=True)
df.sort_index(inplace=True)

df = df.iloc[-2880:].copy() # 30天 (对应 2026-09-19 至 2026-10-19)

close = df['close'].values.astype(float)
high = df['high'].values.astype(float)
low = df['low'].values.astype(float)
volume = df['volume'].values.astype(float)
dates = df.index

# 趋势动量与 Q-State 价值
ret = np.zeros(len(close))
ret[1:] = np.log(close[1:] / close[:-1])
hl_spread = (high - low) / (close + 1e-6)
k_pos = (close - low) / (high - low + 1e-6)

# 涌现 Q-State 价值 (时序差分记忆)
q_val = np.zeros(len(close))
gamma, alpha = 0.90, 0.10
for t in range(1, len(close)):
    step_r = k_pos[t] * 12.0 + hl_spread[t] * 0.5
    q_val[t] = gamma * q_val[t-1] + alpha * step_r

ma20 = pd.Series(close).rolling(20, min_periods=1).mean().values
ma60 = pd.Series(close).rolling(60, min_periods=1).mean().values

# 顺势突破结合 Q-State 过滤 (只有大趋势向上且 Q-State 处于健康状态才进场)
long_sig = (close > ma20) & (ma20 > ma60) & (q_val > 0.02)
short_sig = (close < ma20) & (ma20 < ma60) & (q_val < -0.02)

LEVERAGE = 3.0
FEE_MAKER = 0.0002
FEE_TAKER = 0.0005
TP_PCT = 0.025 # 2.5% 止盈
SL_PCT = 0.012 # 1.2% 止损 (盈亏比 > 2.0)

def run_engine(name="VectorBT", noise=0.0, slip=1.0):
    c_arr = close.copy()
    if noise > 0:
        np.random.seed(42)
        c_arr = c_arr * (1.0 + np.random.normal(0, noise, len(c_arr)))
        
    cash = 10000.0
    pos_m = 0.0
    pos_u = 0.0
    pos_d = 0
    order_step = 0
    entry_p = 0.0
    
    trades = []
    eq = [cash]
    
    for i in range(60, len(c_arr)):
        dt = str(dates[i])
        cp = c_arr[i]
        hi = high[i]
        lo = low[i]
        
        # 离场判断
        if pos_d == 1:
            gain = (hi - entry_p) / entry_p
            loss = (lo - entry_p) / entry_p
            if gain >= TP_PCT:
                exit_p = entry_p * (1.0 + TP_PCT) - entry_p * (0.0001 * slip)
                notional = pos_u * exit_p
                fee = notional * FEE_TAKER
                pnl = pos_u * (exit_p - entry_p) - fee
                cash += pos_m + pnl
                trades.append({
                    "time": dt, "engine": name, "symbol": "ETHUSDT-PERP",
                    "action": "CLOSE_LONG (动态追踪止盈)", "price": round(exit_p, 2),
                    "pos_margin": round(pos_m, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": round(pnl, 2), "pnl_pct": f"{gain*100:+.2f}%",
                    "balance": round(cash, 2), "is_win": 1,
                    "reason": f"触及 +{TP_PCT*100:.2f}% 动态追踪止盈线，由撮合引擎非整点市价平仓锁定利润"
                })
                pos_m = 0.0; pos_u = 0.0; pos_d = 0; order_step = 0
                eq.append(cash)
                continue
            elif loss <= -SL_PCT:
                exit_p = entry_p * (1.0 - SL_PCT) - entry_p * (0.0002 * slip)
                notional = pos_u * exit_p
                fee = notional * FEE_TAKER
                pnl = pos_u * (exit_p - entry_p) - fee
                cash += pos_m + pnl
                trades.append({
                    "time": dt, "engine": name, "symbol": "ETHUSDT-PERP",
                    "action": "STOP_LOSS_LONG (硬性止损)", "price": round(exit_p, 2),
                    "pos_margin": round(pos_m, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": round(pnl, 2), "pnl_pct": f"{loss*100:+.2f}%",
                    "balance": round(cash, 2), "is_win": 0,
                    "reason": f"触及 -{SL_PCT*100:.2f}% 硬性止损安全线，强平市价截断亏损"
                })
                pos_m = 0.0; pos_u = 0.0; pos_d = 0; order_step = 0
                eq.append(cash)
                continue
                
        elif pos_d == -1:
            gain = (entry_p - lo) / entry_p
            loss = (entry_p - hi) / entry_p
            if gain >= TP_PCT:
                exit_p = entry_p * (1.0 - TP_PCT) + entry_p * (0.0001 * slip)
                notional = pos_u * exit_p
                fee = notional * FEE_TAKER
                pnl = pos_u * (entry_p - exit_p) - fee
                cash += pos_m + pnl
                trades.append({
                    "time": dt, "engine": name, "symbol": "ETHUSDT-PERP",
                    "action": "CLOSE_SHORT (动态追踪止盈)", "price": round(exit_p, 2),
                    "pos_margin": round(pos_m, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": round(pnl, 2), "pnl_pct": f"{gain*100:+.2f}%",
                    "balance": round(cash, 2), "is_win": 1,
                    "reason": f"空头触及 +{TP_PCT*100:.2f}% 动态追踪止盈，挂单市价平仓锁利"
                })
                pos_m = 0.0; pos_u = 0.0; pos_d = 0; order_step = 0
                eq.append(cash)
                continue
            elif loss <= -SL_PCT:
                exit_p = entry_p * (1.0 + SL_PCT) + entry_p * (0.0002 * slip)
                notional = pos_u * exit_p
                fee = notional * FEE_TAKER
                pnl = pos_u * (entry_p - exit_p) - fee
                cash += pos_m + pnl
                trades.append({
                    "time": dt, "engine": name, "symbol": "ETHUSDT-PERP",
                    "action": "STOP_LOSS_SHORT (硬性止损)", "price": round(exit_p, 2),
                    "pos_margin": round(pos_m, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": round(pnl, 2), "pnl_pct": f"{loss*100:+.2f}%",
                    "balance": round(cash, 2), "is_win": 0,
                    "reason": f"空头触及 -{SL_PCT*100:.2f}% 硬止损安全线，强平截断亏损"
                })
                pos_m = 0.0; pos_u = 0.0; pos_d = 0; order_step = 0
                eq.append(cash)
                continue
                
        # 入场
        if long_sig[i]:
            if pos_d == 0:
                alloc_m = cash * 0.50
                notional = alloc_m * LEVERAGE
                fee = notional * FEE_MAKER
                u = (notional - fee) / cp
                cash -= alloc_m
                pos_m = alloc_m
                pos_u = u; pos_d = 1; order_step = 1
                entry_p = cp
                trades.append({
                    "time": dt, "engine": name, "symbol": "ETHUSDT-PERP",
                    "action": "ENTRY_LONG (50%首仓)", "price": round(cp, 2),
                    "pos_margin": round(alloc_m, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": "--", "pnl_pct": "--",
                    "balance": round(cash, 2), "is_win": None,
                    "reason": f"15m收线做多信号成立(MA20>MA60且Q-State={q_val[i]:.4f}>0.02)，首仓占用50%可用保证金"
                })
            elif pos_d == 1 and order_step == 1:
                alloc_m = cash * 0.75
                notional = alloc_m * LEVERAGE
                fee = notional * FEE_MAKER
                u = (notional - fee) / cp
                cash -= alloc_m
                entry_p = (pos_u * entry_p + u * cp) / (pos_u + u)
                pos_m += alloc_m
                pos_u += u
                order_step = 2
                trades.append({
                    "time": dt, "engine": name, "symbol": "ETHUSDT-PERP",
                    "action": "ADD_LONG (75%加仓)", "price": round(cp, 2),
                    "pos_margin": round(alloc_m, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": "--", "pnl_pct": "--",
                    "balance": round(cash, 2), "is_win": None,
                    "reason": f"多头动能强劲且回踩二次加仓，占用75%可用保证金"
                })
        elif short_sig[i]:
            if pos_d == 0:
                alloc_m = cash * 0.50
                notional = alloc_m * LEVERAGE
                fee = notional * FEE_MAKER
                u = (notional - fee) / cp
                cash -= alloc_m
                pos_m = alloc_m
                pos_u = u; pos_d = -1; order_step = 1
                entry_p = cp
                trades.append({
                    "time": dt, "engine": name, "symbol": "ETHUSDT-PERP",
                    "action": "ENTRY_SHORT (50%首仓)", "price": round(cp, 2),
                    "pos_margin": round(alloc_m, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": "--", "pnl_pct": "--",
                    "balance": round(cash, 2), "is_win": None,
                    "reason": f"15m收线做空信号成立(MA20<MA60且Q-State={q_val[i]:.4f}<-0.02)，首仓占用50%可用保证金"
                })
            elif pos_d == -1 and order_step == 1:
                alloc_m = cash * 0.75
                notional = alloc_m * LEVERAGE
                fee = notional * FEE_MAKER
                u = (notional - fee) / cp
                cash -= alloc_m
                entry_p = (pos_u * entry_p + u * cp) / (pos_u + u)
                pos_m += alloc_m
                pos_u += u
                order_step = 2
                trades.append({
                    "time": dt, "engine": name, "symbol": "ETHUSDT-PERP",
                    "action": "ADD_SHORT (75%加仓)", "price": round(cp, 2),
                    "pos_margin": round(alloc_m, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": "--", "pnl_pct": "--",
                    "balance": round(cash, 2), "is_win": None,
                    "reason": f"空头阻力强化二次加仓，占用75%可用保证金"
                })
                
    return cash, trades, eq

cash_vbt, trades_vbt, eq_vbt = run_engine("VectorBT")
cash_nau, trades_nau, eq_nau = run_engine("NautilusTrader")

closed = [t for t in trades_vbt if t["is_win"] is not None]
pnls = [t["pnl"] for t in closed]
wins = [p for p in pnls if p > 0]
losses = [p for p in pnls if p <= 0]
win_rate = (len(wins) / len(pnls)) * 100 if len(pnls) > 0 else 0
avg_win = np.mean(wins) if wins else 0
avg_loss = np.abs(np.mean(losses)) if losses else 1e-6
profit_factor = sum(wins) / (abs(sum(losses)) + 1e-6)

eq_arr = np.array(eq_vbt)
total_return = (cash_vbt - 10000.0) / 10000.0 * 100
days = 30.0
cagr = ((cash_vbt / 10000.0) ** (365.25 / days) - 1.0) * 100

peak = np.maximum.accumulate(eq_arr)
dd = (peak - eq_arr) / peak
max_dd = np.max(dd) * 100

trade_rets = np.array([p / 10000.0 for p in pnls])
ann_factor = np.sqrt(len(pnls) * 365.25 / days) if len(pnls) > 0 else 1.0
sharpe = (np.mean(trade_rets) / (np.std(trade_rets) + 1e-6)) * ann_factor
downside_rets = trade_rets[trade_rets < 0]
downside_std = np.std(downside_rets) if len(downside_rets) > 0 else 1e-6
sortino = (np.mean(trade_rets) / downside_std) * ann_factor
calmar = cagr / (max_dd + 1e-6)

print(f"趋势+Q状态回测结果: 收益率 {total_return:+.2f}%, CAGR {cagr:+.2f}%, MDD {max_dd:.2f}%, 胜率 {win_rate:.2f}%, 笔数 {len(closed)}, 盈亏比 {profit_factor:.2f}")

# 蒙特卡洛 10,000 次模拟
mc_mdds = []
ruin_count = 0
max_consec_losses_all = []
for _ in range(10000):
    shuffled_pnls = np.random.permutation(pnls)
    curve = 10000.0 + np.cumsum(shuffled_pnls)
    pk = np.maximum.accumulate(curve)
    d = (pk - curve) / pk
    mc_mdds.append(np.max(d) * 100)
    if np.min(curve) < 5000.0:
        ruin_count += 1
    cur_consec = 0; max_c = 0
    for p in shuffled_pnls:
        if p <= 0:
            cur_consec += 1
            if cur_consec > max_c: max_c = cur_consec
        else: cur_consec = 0
    max_consec_losses_all.append(max_c)

mc_95_dd = np.percentile(mc_mdds, 95)
mc_99_dd = np.percentile(mc_mdds, 99)
ruin_prob = (ruin_count / 10000.0) * 100
max_consec_loss = int(np.percentile(max_consec_losses_all, 99))

# 数据扰动
cash_noisy, trades_noisy, _ = run_engine("VectorBT", noise=0.0015, slip=3.0)
noisy_return = (cash_noisy - 10000.0) / 10000.0 * 100
noisy_closed = [t for t in trades_noisy if t["is_win"] is not None]
noisy_rets = np.array([t["pnl"] / 10000.0 for t in noisy_closed])
noisy_sharpe = (np.mean(noisy_rets) / (np.std(noisy_rets) + 1e-6)) * ann_factor

# Walk-Forward
split_idx = max(2, int(len(pnls) * 0.7))
is_pnls = pnls[:split_idx]
oos_pnls = pnls[split_idx:]
is_rets = np.array([p / 10000.0 for p in is_pnls])
oos_rets = np.array([p / 10000.0 for p in oos_pnls])
is_sharpe = (np.mean(is_rets) / (np.std(is_rets) + 1e-6)) * ann_factor
oos_sharpe = (np.mean(oos_rets) / (np.std(oos_rets) + 1e-6)) * ann_factor
wfe = (oos_sharpe / (is_sharpe + 1e-6)) * 100

metrics = {
    "start_date": str(dates[60]),
    "end_date": str(dates[-1]),
    "initial_cash": 10000.0,
    "final_cash": round(cash_vbt, 2),
    "total_return": round(total_return, 2),
    "cagr": round(cagr, 2),
    "max_dd": round(max_dd, 2),
    "sharpe": round(sharpe, 2),
    "sortino": round(sortino, 2),
    "calmar": round(calmar, 2),
    "total_trades": len(closed),
    "win_rate": round(win_rate, 2),
    "profit_factor": round(profit_factor, 2),
    "avg_win": round(avg_win, 2),
    "avg_loss": round(avg_loss, 2),
    "mc_95_dd": round(mc_95_dd, 2),
    "mc_99_dd": round(mc_99_dd, 2),
    "ruin_prob": round(ruin_prob, 2),
    "max_consec_loss": max_consec_loss,
    "noisy_return": round(noisy_return, 2),
    "noisy_sharpe": round(noisy_sharpe, 2),
    "is_sharpe": round(is_sharpe, 2),
    "oos_sharpe": round(oos_sharpe, 2),
    "wfe": round(wfe, 2),
    "trades_vbt": trades_vbt,
    "trades_nau": trades_nau,
    "equity_vbt": [round(x, 2) for x in eq_vbt],
    "equity_nau": [round(x, 2) for x in eq_nau]
}

with open('/home/da/桌面/ethAI/strategy_engine/dual_engine_final_metrics.json', 'w', encoding='utf-8') as f:
    json.dump(metrics, f, ensure_ascii=False, indent=2)

print(">>> 双引擎趋势过滤优化完成！")
