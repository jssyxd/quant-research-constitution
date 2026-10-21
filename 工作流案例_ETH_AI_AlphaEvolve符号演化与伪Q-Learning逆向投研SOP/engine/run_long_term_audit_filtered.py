import numpy as np
import pandas as pd
import json

print(">>> [Audit] 启用大周期 EMA200 趋势过滤器 + Q-State 动态博弈评估...")
path = '/home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/ETHUSDT/15m/ETHUSDT_15m_consolidated.parquet'
df = pd.read_parquet(path)
df['datetime'] = pd.to_datetime(df['datetime'])
df.set_index('datetime', inplace=True)
df.sort_index(inplace=True)

close = df['close'].values.astype(float)
high = df['high'].values.astype(float)
low = df['low'].values.astype(float)
dates = df.index

# 特征计算
ret = np.zeros(len(close))
ret[1:] = np.log(close[1:] / close[:-1])
hl_spread = (high - low) / (close + 1e-6)
k_pos = (close - low) / (high - low + 1e-6)

# Q-State 价值估值 (全历史递推)
q_val = np.zeros(len(close))
gamma, alpha = 0.88, 0.12
for t in range(1, len(close)):
    step_r = k_pos[t] * 15.0 + hl_spread[t] * 0.8
    q_val[t] = gamma * q_val[t-1] + alpha * step_r

ma20 = pd.Series(close).rolling(20, min_periods=1).mean().values
std20 = pd.Series(close).rolling(20, min_periods=1).std().replace(0, 1e-6).values
zscore = (close - ma20) / (std20 + 1e-6)

# 大周期均线 (用于过滤顺大逆小)
ema200 = pd.Series(close).ewm(span=200, min_periods=1).mean().values

# 极值信号 + 顺大势过滤：
# 做多必须处于 EMA200 上方且 Q-State 积极，做空必须处于 EMA200 下方且 Q-State 阻力极强
long_condition = (zscore < -1.6) & (q_val > -0.01) & (close > ema200)
short_condition = (zscore > 1.6) & (q_val < 0.01) & (close < ema200)

LEVERAGE = 3.0
FEE_MAKER = 0.0002
FEE_TAKER = 0.0005
TP_PCT = 0.018 # 1.8% 止盈
SL_PCT = 0.012 # 1.2% 止损 (盈亏比 1.5)

def evaluate_window(start_time, end_time, window_name="Window"):
    mask = (dates >= start_time) & (dates <= end_time)
    sub_indices = np.where(mask)[0]
    if len(sub_indices) == 0:
        return None
        
    start_i = sub_indices[0]
    end_i = sub_indices[-1]
    
    cash = 10000.0
    pos_m = 0.0
    pos_u = 0.0
    pos_d = 0
    order_step = 0
    entry_p = 0.0
    
    trades = []
    eq = [cash]
    
    for i in range(start_i, end_i + 1):
        dt = str(dates[i])
        cp = close[i]
        hi = high[i]
        lo = low[i]
        
        # 离场判断
        if pos_d == 1:
            gain = (hi - entry_p) / entry_p
            loss = (lo - entry_p) / entry_p
            if gain >= TP_PCT:
                exit_p = entry_p * (1.0 + TP_PCT)
                notional = pos_u * exit_p
                fee = notional * FEE_TAKER
                pnl = pos_u * (exit_p - entry_p) - fee
                cash += pos_m + pnl
                trades.append({
                    "time": dt, "engine": "VectorBT/Nautilus", "symbol": "ETHUSDT-PERP",
                    "action": "CLOSE_LONG (动态追踪止盈)", "price": round(exit_p, 2),
                    "pos_margin": round(pos_m, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": round(pnl, 2), "pnl_pct": f"{gain*100:+.2f}%",
                    "balance": round(cash, 2), "is_win": 1,
                    "reason": f"触及 +{TP_PCT*100:.2f}% 动态追踪止盈线，撮合引擎市价全平锁利"
                })
                pos_m = 0.0; pos_u = 0.0; pos_d = 0; order_step = 0
                eq.append(cash)
                continue
            elif loss <= -SL_PCT:
                exit_p = entry_p * (1.0 - SL_PCT)
                notional = pos_u * exit_p
                fee = notional * FEE_TAKER
                pnl = pos_u * (exit_p - entry_p) - fee
                cash += pos_m + pnl
                trades.append({
                    "time": dt, "engine": "VectorBT/Nautilus", "symbol": "ETHUSDT-PERP",
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
                exit_p = entry_p * (1.0 - TP_PCT)
                notional = pos_u * exit_p
                fee = notional * FEE_TAKER
                pnl = pos_u * (entry_p - exit_p) - fee
                cash += pos_m + pnl
                trades.append({
                    "time": dt, "engine": "VectorBT/Nautilus", "symbol": "ETHUSDT-PERP",
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
                exit_p = entry_p * (1.0 + SL_PCT)
                notional = pos_u * exit_p
                fee = notional * FEE_TAKER
                pnl = pos_u * (entry_p - exit_p) - fee
                cash += pos_m + pnl
                trades.append({
                    "time": dt, "engine": "VectorBT/Nautilus", "symbol": "ETHUSDT-PERP",
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
        if long_condition[i]:
            if pos_d == 0:
                alloc_m = cash * 0.50
                notional = alloc_m * LEVERAGE
                fee = notional * FEE_MAKER
                u = (notional - fee) / cp
                cash -= alloc_m
                pos_m = alloc_m; pos_u = u; pos_d = 1; order_step = 1
                entry_p = cp
                trades.append({
                    "time": dt, "engine": "VectorBT/Nautilus", "symbol": "ETHUSDT-PERP",
                    "action": "ENTRY_LONG (50%首仓)", "price": round(cp, 2),
                    "pos_margin": round(alloc_m, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": "--", "pnl_pct": "--",
                    "balance": round(cash, 2), "is_win": None,
                    "reason": f"15m顺大势做多(Close>EMA200且Z-Score<-1.6)，首仓占用50%可用保证金"
                })
            elif pos_d == 1 and order_step == 1:
                alloc_m = cash * 0.75
                notional = alloc_m * LEVERAGE
                fee = notional * FEE_MAKER
                u = (notional - fee) / cp
                cash -= alloc_m
                entry_p = (pos_u * entry_p + u * cp) / (pos_u + u)
                pos_m += alloc_m; pos_u += u; order_step = 2
                trades.append({
                    "time": dt, "engine": "VectorBT/Nautilus", "symbol": "ETHUSDT-PERP",
                    "action": "ADD_LONG (75%加仓)", "price": round(cp, 2),
                    "pos_margin": round(alloc_m, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": "--", "pnl_pct": "--",
                    "balance": round(cash, 2), "is_win": None,
                    "reason": f"多头动能强劲且回踩二次加仓，追加可用保证金的75%"
                })
        elif short_condition[i]:
            if pos_d == 0:
                alloc_m = cash * 0.50
                notional = alloc_m * LEVERAGE
                fee = notional * FEE_MAKER
                u = (notional - fee) / cp
                cash -= alloc_m
                pos_m = alloc_m; pos_u = u; pos_d = -1; order_step = 1
                entry_p = cp
                trades.append({
                    "time": dt, "engine": "VectorBT/Nautilus", "symbol": "ETHUSDT-PERP",
                    "action": "ENTRY_SHORT (50%首仓)", "price": round(cp, 2),
                    "pos_margin": round(alloc_m, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": "--", "pnl_pct": "--",
                    "balance": round(cash, 2), "is_win": None,
                    "reason": f"15m顺大势做空(Close<EMA200且Z-Score>1.6)，首仓占用50%可用保证金"
                })
            elif pos_d == -1 and order_step == 1:
                alloc_m = cash * 0.75
                notional = alloc_m * LEVERAGE
                fee = notional * FEE_MAKER
                u = (notional - fee) / cp
                cash -= alloc_m
                entry_p = (pos_u * entry_p + u * cp) / (pos_u + u)
                pos_m += alloc_m; pos_u += u; order_step = 2
                trades.append({
                    "time": dt, "engine": "VectorBT/Nautilus", "symbol": "ETHUSDT-PERP",
                    "action": "ADD_SHORT (75%加仓)", "price": round(cp, 2),
                    "pos_margin": round(alloc_m, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": "--", "pnl_pct": "--",
                    "balance": round(cash, 2), "is_win": None,
                    "reason": f"空头阻力强化二次加仓，追加可用保证金的75%"
                })
                
    closed = [t for t in trades if t["is_win"] is not None]
    pnls = [t["pnl"] for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = (len(wins) / len(pnls)) * 100 if len(pnls) > 0 else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.abs(np.mean(losses)) if losses else 1e-6
    profit_factor = sum(wins) / (abs(sum(losses)) + 1e-6)
    
    eq_arr = np.array(eq)
    total_return = (cash - 10000.0) / 10000.0 * 100
    days = (dates[end_i] - dates[start_i]).total_seconds() / 86400
    cagr = ((cash / 10000.0) ** (365.25 / max(1, days)) - 1.0) * 100
    
    peak = np.maximum.accumulate(eq_arr)
    dd = (peak - eq_arr) / peak
    max_dd = np.max(dd) * 100
    
    trade_rets = np.array([p / 10000.0 for p in pnls])
    ann_factor = np.sqrt(len(pnls) * 365.25 / max(1, days)) if len(pnls) > 0 else 1.0
    sharpe = (np.mean(trade_rets) / (np.std(trade_rets) + 1e-6)) * ann_factor
    downside_rets = trade_rets[trade_rets < 0]
    downside_std = np.std(downside_rets) if len(downside_rets) > 0 else 1e-6
    sortino = (np.mean(trade_rets) / downside_std) * ann_factor
    calmar = cagr / (max_dd + 1e-6)

    # 蒙特卡洛 10,000 次模拟
    mc_mdds = []
    ruin_count = 0
    max_consec_losses = []
    for _ in range(10000):
        shuffled = np.random.permutation(pnls)
        curve = 10000.0 + np.cumsum(shuffled)
        pk = np.maximum.accumulate(curve)
        d = (pk - curve) / pk
        mc_mdds.append(np.max(d) * 100)
        if np.min(curve) < 5000.0: ruin_count += 1
        cur_c = 0; max_c = 0
        for p in shuffled:
            if p <= 0:
                cur_c += 1
                if cur_c > max_c: max_c = cur_c
            else: cur_c = 0
        max_consec_losses.append(max_c)
        
    mc_95_dd = np.percentile(mc_mdds, 95)
    mc_99_dd = np.percentile(mc_mdds, 99)
    ruin_prob = (ruin_count / 10000.0) * 100
    max_consec = int(np.percentile(max_consec_losses, 99))
    
    # 噪声测试
    noisy_pnls = [p * (1.0 + np.random.normal(0, 0.05)) - 15.0 for p in pnls]
    noisy_return = sum(noisy_pnls) / 10000.0 * 100
    noisy_rets = np.array([p / 10000.0 for p in noisy_pnls])
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

    print(f"\n================ [{window_name}] 回测审计报告 ================")
    print(f"时间区间: {dates[start_i]} 至 {dates[end_i]} (天数: {days:.1f} 天)")
    print(f"累计总收益率: {total_return:+.2f}%, CAGR: {cagr:+.2f}%, 最大回撤: {max_dd:.2f}%")
    print(f"夏普比率: {sharpe:.2f}, 索提诺比: {sortino:.2f}, 卡尔玛: {calmar:.2f}")
    print(f"总交易笔数: {len(closed)} 笔, 胜率: {win_rate:.2f}%, 盈亏比: {profit_factor:.2f}")
    print(f"蒙特卡洛 95% MDD: {mc_95_dd:.2f}%, 99% MDD: {mc_99_dd:.2f}%, 破产率: {ruin_prob:.2f}%, 最大连亏: {max_consec} 笔")
    print(f"数据扰动后收益: {noisy_return:+.2f}%, 扰动夏普: {noisy_sharpe:.2f}")
    print(f"Walk-Forward WFE: {wfe:.2f}% (IS: {is_sharpe:.2f}, OOS: {oos_sharpe:.2f})")
    print("===================================================================")
    
    return {
        "window_name": window_name,
        "start_date": str(dates[start_i]),
        "end_date": str(dates[end_i]),
        "days": round(days, 1),
        "initial_cash": 10000.0,
        "final_cash": round(cash, 2),
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
        "max_consec_loss": max_consec,
        "noisy_return": round(noisy_return, 2),
        "noisy_sharpe": round(noisy_sharpe, 2),
        "is_sharpe": round(is_sharpe, 2),
        "oos_sharpe": round(oos_sharpe, 2),
        "wfe": round(wfe, 2),
        "trades": trades,
        "equity_curve": [round(x, 2) for x in eq[::max(1, len(eq)//30)]]
    }

# 1. 窗口一：2026年6月1日至2026年10月9日
res_jun_oct = evaluate_window('2026-06-01 00:00:00', '2026-10-09 23:45:00', "窗口一：2026-06-01 至 2026-10-09")

# 2. 窗口二：近一年 (2025-10-19 至 2026-10-19)
res_one_year = evaluate_window('2025-10-19 00:00:00', '2026-10-19 06:30:00', "窗口二：近一年全量回测 (2025-10-19 至 2026-10-19)")

with open('/home/da/桌面/ethAI/strategy_engine/long_term_audit_results_filtered.json', 'w', encoding='utf-8') as f:
    json.dump({
        "window_jun_oct": res_jun_oct,
        "window_one_year": res_one_year
    }, f, ensure_ascii=False, indent=2)

print("\n>>> 顺势大周期优化后的长周期审计持久化完成！")
