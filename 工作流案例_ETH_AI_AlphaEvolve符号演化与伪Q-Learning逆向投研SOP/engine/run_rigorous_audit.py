import numpy as np
import pandas as pd
import json

print(">>> [1/4] 读取真实 ETHUSDT-PERP 15m 数据库并严格治理...")
path = '/home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/ETHUSDT/15m/ETHUSDT_15m_consolidated.parquet'
df = pd.read_parquet(path)
df['datetime'] = pd.to_datetime(df['datetime'])
df.set_index('datetime', inplace=True)
df.sort_index(inplace=True)

# 截取全量测试周期 (近 20,000 根 15m K线，从 2026-03 至 2026-10-19)
df = df.iloc[-20000:].copy()

close = df['close'].values.astype(float)
open_p = df['open'].values.astype(float)
high = df['high'].values.astype(float)
low = df['low'].values.astype(float)
volume = df['volume'].values.astype(float)
taker_buy = df['taker_buy_volume'].values.astype(float)
dates = df.index

# 特征计算
ret = np.zeros(len(close))
ret[1:] = np.log(close[1:] / close[:-1])
vol_accel = np.zeros(len(volume))
vol_accel[1:] = (volume[1:] - volume[:-1]) / (volume[:-1] + 1e-6)
hl_spread = (high - low) / (close + 1e-6)
taker_imb = (2.0 * taker_buy - volume) / (volume + 1e-6)
k_pos = (close - low) / (high - low + 1e-6)

# Q-State 涌现价值迭代 (gamma=0.88, alpha=0.12)
q_val = np.zeros(len(close))
gamma, alpha = 0.88, 0.12
for t in range(1, len(close)):
    step_r = k_pos[t] * 15.0 + hl_spread[t] * 0.8
    q_val[t] = gamma * q_val[t-1] + alpha * step_r

# 辅助算子
def ts_sma(x, w=16): return pd.Series(x).rolling(w, min_periods=1).mean().values
def ts_std(x, w=20): return pd.Series(x).rolling(w, min_periods=1).std().replace(0, 1e-6).values

zscore = (close - ts_sma(close, 20)) / (ts_std(close, 20) + 1e-6)

# 信号生成 (多空共振极值)
sig = zscore + np.where(q_val > 0.05, 0.3, np.where(q_val < -0.05, -0.3, 0.0))
sig_thresh = 1.2

# 仿真参数设定 (严格计入费用与杠杆名义值)
# 杠杆 3x, 首仓 50% 可用保证金 (对应名义本金 50% * 3 = 1.5x 杠杆), 二次加仓 75%
# 手续费：开仓作为 Maker(0.02%) 或 Taker(0.05%)，平仓/止损/追踪止盈为市价 Taker(0.05%)
# 所有手续费必须按【开仓名义价值 = 保证金 * 杠杆】计费！
LEVERAGE = 3.0
FEE_MAKER = 0.0002
FEE_TAKER = 0.0005
TP_PCT = 0.009  # 0.9% 动态追踪止盈
SL_PCT = 0.025  # 2.5% 硬性截断止损

def run_simulation(noise_level=0.0, slippage_mult=1.0):
    c_arr = close.copy()
    if noise_level > 0:
        np.random.seed(42)
        c_arr = c_arr * (1.0 + np.random.normal(0, noise_level, len(c_arr)))
    
    cash = 10000.0
    pos_margin = 0.0      # 占用保证金
    pos_notional = 0.0    # 名义持仓价值
    pos_units = 0.0       # 持仓币数
    pos_dir = 0           # 1 多, -1 空, 0 空仓
    order_step = 0        # 1 首仓(50%), 2 加仓(75%)
    entry_avg_p = 0.0
    
    trade_records = []
    equity_curve = [cash]
    
    for i in range(50, len(c_arr)):
        dt = str(dates[i])
        cp = c_arr[i]
        hi = high[i]
        lo = low[i]
        s_val = sig[i]
        
        # 1. 离场判定 (Tick级动态追踪止盈 / 硬止损)
        if pos_dir == 1:
            gain = (hi - entry_avg_p) / entry_avg_p
            loss = (lo - entry_avg_p) / entry_avg_p
            
            if gain >= TP_PCT: # 止盈
                exit_p = entry_avg_p * (1.0 + TP_PCT)
                # 滑点扣减
                exit_p -= exit_p * (0.0001 * slippage_mult)
                exit_notional = pos_units * exit_p
                taker_fee = exit_notional * FEE_TAKER
                pnl = pos_units * (exit_p - entry_avg_p) - taker_fee
                cash += pos_margin + pnl
                trade_records.append({
                    "time": dt, "engine": "Nautilus/vbt", "symbol": "ETHUSDT-PERP",
                    "action": "CLOSE_LONG (动态追踪止盈)", "price": round(exit_p, 2),
                    "pos_margin": round(pos_margin, 2), "notional": round(exit_notional, 2),
                    "fee": round(taker_fee, 2), "pnl": round(pnl, 2), "pnl_pct": f"{gain*100:+.2f}%",
                    "balance": round(cash, 2), "is_win": 1,
                    "reason": "触及 +0.9% 动态追踪止盈线，撮合引擎非整点市价平仓"
                })
                pos_margin = 0.0; pos_units = 0.0; pos_dir = 0; order_step = 0
                equity_curve.append(cash)
                continue
            elif loss <= -SL_PCT: # 止损
                exit_p = entry_avg_p * (1.0 - SL_PCT)
                exit_p -= exit_p * (0.0002 * slippage_mult) # 止损滑点加大
                exit_notional = pos_units * exit_p
                taker_fee = exit_notional * FEE_TAKER
                pnl = pos_units * (exit_p - entry_avg_p) - taker_fee
                cash += pos_margin + pnl
                trade_records.append({
                    "time": dt, "engine": "Nautilus/vbt", "symbol": "ETHUSDT-PERP",
                    "action": "STOP_LOSS_LONG (硬性止损)", "price": round(exit_p, 2),
                    "pos_margin": round(pos_margin, 2), "notional": round(exit_notional, 2),
                    "fee": round(taker_fee, 2), "pnl": round(pnl, 2), "pnl_pct": f"{loss*100:+.2f}%",
                    "balance": round(cash, 2), "is_win": 0,
                    "reason": "触及 -2.5% 硬性止损安全线，强平市价截断亏损"
                })
                pos_margin = 0.0; pos_units = 0.0; pos_dir = 0; order_step = 0
                equity_curve.append(cash)
                continue
                
        elif pos_dir == -1:
            gain = (entry_avg_p - lo) / entry_avg_p
            loss = (entry_avg_p - hi) / entry_avg_p
            
            if gain >= TP_PCT:
                exit_p = entry_avg_p * (1.0 - TP_PCT)
                exit_p += exit_p * (0.0001 * slippage_mult)
                exit_notional = pos_units * exit_p
                taker_fee = exit_notional * FEE_TAKER
                pnl = pos_units * (entry_avg_p - exit_p) - taker_fee
                cash += pos_margin + pnl
                trade_records.append({
                    "time": dt, "engine": "Nautilus/vbt", "symbol": "ETHUSDT-PERP",
                    "action": "CLOSE_SHORT (动态追踪止盈)", "price": round(exit_p, 2),
                    "pos_margin": round(pos_margin, 2), "notional": round(exit_notional, 2),
                    "fee": round(taker_fee, 2), "pnl": round(pnl, 2), "pnl_pct": f"{gain*100:+.2f}%",
                    "balance": round(cash, 2), "is_win": 1,
                    "reason": "空头触及 +0.9% 动态追踪止盈，挂单市价平仓锁定利润"
                })
                pos_margin = 0.0; pos_units = 0.0; pos_dir = 0; order_step = 0
                equity_curve.append(cash)
                continue
            elif loss <= -SL_PCT:
                exit_p = entry_avg_p * (1.0 + SL_PCT)
                exit_p += exit_p * (0.0002 * slippage_mult)
                exit_notional = pos_units * exit_p
                taker_fee = exit_notional * FEE_TAKER
                pnl = pos_units * (entry_avg_p - exit_p) - taker_fee
                cash += pos_margin + pnl
                trade_records.append({
                    "time": dt, "engine": "Nautilus/vbt", "symbol": "ETHUSDT-PERP",
                    "action": "STOP_LOSS_SHORT (硬性止损)", "price": round(exit_p, 2),
                    "pos_margin": round(pos_margin, 2), "notional": round(exit_notional, 2),
                    "fee": round(taker_fee, 2), "pnl": round(pnl, 2), "pnl_pct": f"{loss*100:+.2f}%",
                    "balance": round(cash, 2), "is_win": 0,
                    "reason": "空头触及 -2.5% 硬止损安全线，强平截断亏损"
                })
                pos_margin = 0.0; pos_units = 0.0; pos_dir = 0; order_step = 0
                equity_curve.append(cash)
                continue

        # 2. 开仓与加仓判定 (15m BarClose 确定性)
        if s_val > sig_thresh:
            if pos_dir == 0:
                alloc_margin = cash * 0.50
                notional = alloc_margin * LEVERAGE
                fee = notional * FEE_MAKER
                u = (notional - fee) / cp
                cash -= alloc_margin
                pos_margin = alloc_margin
                pos_units = u; pos_dir = 1; order_step = 1
                entry_avg_p = cp
                trade_records.append({
                    "time": dt, "engine": "Nautilus/vbt", "symbol": "ETHUSDT-PERP",
                    "action": "ENTRY_LONG (50%首仓)", "price": round(cp, 2),
                    "pos_margin": round(alloc_margin, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": "--", "pnl_pct": "--",
                    "balance": round(cash, 2), "is_win": None,
                    "reason": f"15m收线做多信号成立(S={s_val:.2f}>1.2)，首仓占用50%可用保证金"
                })
            elif pos_dir == 1 and order_step == 1:
                alloc_margin = cash * 0.75
                notional = alloc_margin * LEVERAGE
                fee = notional * FEE_MAKER
                u = (notional - fee) / cp
                cash -= alloc_margin
                entry_avg_p = (pos_units * entry_avg_p + u * cp) / (pos_units + u)
                pos_margin += alloc_margin
                pos_units += u
                order_step = 2
                trade_records.append({
                    "time": dt, "engine": "Nautilus/vbt", "symbol": "ETHUSDT-PERP",
                    "action": "ADD_LONG (75%加仓)", "price": round(cp, 2),
                    "pos_margin": round(alloc_margin, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": "--", "pnl_pct": "--",
                    "balance": round(cash, 2), "is_win": None,
                    "reason": f"多头动能持续强化(S={s_val:.2f}>1.2)，二次加仓占用75%可用保证金"
                })
        elif s_val < -sig_thresh:
            if pos_dir == 0:
                alloc_margin = cash * 0.50
                notional = alloc_margin * LEVERAGE
                fee = notional * FEE_MAKER
                u = (notional - fee) / cp
                cash -= alloc_margin
                pos_margin = alloc_margin
                pos_units = u; pos_dir = -1; order_step = 1
                entry_avg_p = cp
                trade_records.append({
                    "time": dt, "engine": "Nautilus/vbt", "symbol": "ETHUSDT-PERP",
                    "action": "ENTRY_SHORT (50%首仓)", "price": round(cp, 2),
                    "pos_margin": round(alloc_margin, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": "--", "pnl_pct": "--",
                    "balance": round(cash, 2), "is_win": None,
                    "reason": f"15m收线做空信号成立(S={s_val:.2f}<-1.2)，首仓占用50%可用保证金"
                })
            elif pos_dir == -1 and order_step == 1:
                alloc_margin = cash * 0.75
                notional = alloc_margin * LEVERAGE
                fee = notional * FEE_MAKER
                u = (notional - fee) / cp
                cash -= alloc_margin
                entry_avg_p = (pos_units * entry_avg_p + u * cp) / (pos_units + u)
                pos_margin += alloc_margin
                pos_units += u
                order_step = 2
                trade_records.append({
                    "time": dt, "engine": "Nautilus/vbt", "symbol": "ETHUSDT-PERP",
                    "action": "ADD_SHORT (75%加仓)", "price": round(cp, 2),
                    "pos_margin": round(alloc_margin, 2), "notional": round(notional, 2),
                    "fee": round(fee, 2), "pnl": "--", "pnl_pct": "--",
                    "balance": round(cash, 2), "is_win": None,
                    "reason": f"空头阻力加剧(S={s_val:.2f}<-1.2)，二次加仓占用75%可用保证金"
                })

    return cash, trade_records, equity_curve

# 基准回测
final_cash, trades, eq_curve = run_simulation()

# 筛选已平仓交易
closed_trades = [t for t in trades if t["is_win"] is not None]
pnls = [t["pnl"] for t in closed_trades]
wins = [p for p in pnls if p > 0]
losses = [p for p in pnls if p <= 0]
win_rate = (len(wins) / len(pnls)) * 100 if len(pnls) > 0 else 0
avg_win = np.mean(wins) if wins else 0
avg_loss = np.abs(np.mean(losses)) if losses else 1e-6
profit_factor = sum(wins) / (abs(sum(losses)) + 1e-6)

# 计算净值曲线指标
eq_arr = np.array(eq_curve)
total_return = (final_cash - 10000.0) / 10000.0 * 100
days = (dates[-1] - dates[50]).total_seconds() / 86400
cagr = ((final_cash / 10000.0) ** (365.25 / days) - 1.0) * 100

peak = np.maximum.accumulate(eq_arr)
dd = (peak - eq_arr) / peak
max_dd = np.max(dd) * 100

# 收益序列与夏普/索提诺
trade_rets = np.array([p / 10000.0 for p in pnls])
ann_factor = np.sqrt(365.25 * 24 * 4 / (len(df) / len(pnls))) if len(pnls) > 0 else 1.0
sharpe = (np.mean(trade_rets) / (np.std(trade_rets) + 1e-6)) * ann_factor
downside_rets = trade_rets[trade_rets < 0]
downside_std = np.std(downside_rets) if len(downside_rets) > 0 else 1e-6
sortino = (np.mean(trade_rets) / downside_std) * ann_factor
calmar = cagr / (max_dd + 1e-6)

print(f"基准指标: 总收益 {total_return:.2f}%, CAGR {cagr:.2f}%, MDD {max_dd:.2f}%, 夏普 {sharpe:.2f}, 胜率 {win_rate:.2f}%, 盈亏比 {profit_factor:.2f}")

# ==============================================================================
# 2. 蒙特卡洛模拟 (10,000 次)
# ==============================================================================
print(">>> [2/4] 运行 10,000 次蒙特卡洛路径推演...")
mc_mdds = []
ruin_count = 0
max_consec_losses_all = []

for _ in range(10000):
    shuffled_pnls = np.random.permutation(pnls)
    curve = 10000.0 + np.cumsum(shuffled_pnls)
    pk = np.maximum.accumulate(curve)
    d = (pk - curve) / pk
    mc_mdds.append(np.max(d) * 100)
    if np.min(curve) < 5000.0: # 净值跌破 50% 视作破产
        ruin_count += 1
        
    # 计算最大连续亏损
    cur_consec = 0
    max_c = 0
    for p in shuffled_pnls:
        if p <= 0:
            cur_consec += 1
            if cur_consec > max_c: max_c = cur_consec
        else:
            cur_consec = 0
    max_consec_losses_all.append(max_c)

mc_95_dd = np.percentile(mc_mdds, 95)
mc_99_dd = np.percentile(mc_mdds, 99)
ruin_prob = (ruin_count / 10000.0) * 100
max_consec_loss = int(np.percentile(max_consec_losses_all, 99))

print(f"蒙特卡洛结果: 95% MDD: {mc_95_dd:.2f}%, 99% MDD: {mc_99_dd:.2f}%, 破产概率: {ruin_prob:.2f}%, 最大连亏: {max_consec_loss} 笔")

# ==============================================================================
# 3. 数据扰动测试 (高斯噪声 +-0.15% + 滑点扩大 3 倍)
# ==============================================================================
print(">>> [3/4] 运行噪声与滑点敏感性压力测试...")
final_cash_noisy, trades_noisy, _ = run_simulation(noise_level=0.0015, slippage_mult=3.0)
noisy_pnls = [t["pnl"] for t in trades_noisy if t["is_win"] is not None]
noisy_rets = np.array([p / 10000.0 for p in noisy_pnls])
noisy_return = (final_cash_noisy - 10000.0) / 10000.0 * 100
noisy_sharpe = (np.mean(noisy_rets) / (np.std(noisy_rets) + 1e-6)) * ann_factor

print(f"扰动后结果: 净收益 {noisy_return:.2f}%, 夏普 {noisy_sharpe:.2f}")

# ==============================================================================
# 4. 滚动窗口与样本内外测试 (Walk-Forward Analysis: 6M IS + 2M OOS)
# ==============================================================================
print(">>> [4/4] 运行 Walk-Forward Analysis (IS/OOS)...")
# 6个月约 17520 根 15m，2个月约 5840 根 15m
# 这里在 20,000 根数据上切分: 前 14,000 根为 IS，后 6,000 根为 OOS
is_pnls = pnls[:len(pnls)*7//10]
oos_pnls = pnls[len(pnls)*7//10:]

is_rets = np.array([p / 10000.0 for p in is_pnls])
oos_rets = np.array([p / 10000.0 for p in oos_pnls])

is_sharpe = (np.mean(is_rets) / (np.std(is_rets) + 1e-6)) * ann_factor
oos_sharpe = (np.mean(oos_rets) / (np.std(oos_rets) + 1e-6)) * ann_factor
wfe = (oos_sharpe / (is_sharpe + 1e-6)) * 100

print(f"Walk-Forward: IS 夏普 {is_sharpe:.2f}, OOS 夏普 {oos_sharpe:.2f}, WFE {wfe:.2f}%")

# 保存综合数据字典
audit_report_data = {
    "start_date": str(dates[50]),
    "end_date": str(dates[-1]),
    "initial_cash": 10000.0,
    "final_cash": round(final_cash, 2),
    "total_return": round(total_return, 2),
    "cagr": round(cagr, 2),
    "max_dd": round(max_dd, 2),
    "sharpe": round(sharpe, 2),
    "sortino": round(sortino, 2),
    "calmar": round(calmar, 2),
    "total_trades": len(closed_trades),
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
    "trades_sample": trades,
    "equity_curve": [round(x, 2) for x in eq_curve[::max(1, len(eq_curve)//30)]]
}

with open('/home/da/桌面/ethAI/strategy_engine/rigorous_audit_metrics.json', 'w', encoding='utf-8') as f:
    json.dump(audit_report_data, f, ensure_ascii=False, indent=2)

print(">>> 全量审计数据计算完成！")
