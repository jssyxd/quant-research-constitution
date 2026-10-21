import numpy as np
import pandas as pd
import json

# 加载真实 1h 数据 (使用完整的 10000 根真实 K 线)
data_path = '/home/da/桌面/database/01_raw_lake/cryptodatadownload/bitstamp/Bitstamp_ETHUSDT_1h.csv'
df = pd.read_csv(data_path, skiprows=1)
df = df.iloc[::-1].reset_index(drop=True)
df['date'] = pd.to_datetime(df['date'])
df.set_index('date', inplace=True)

df = df.iloc[-6000:].copy() # 最近 250 天真实行情

close = df['close'].values
high = df['high'].values
low = df['low'].values
volume = df['Volume ETH'].values
dates = df.index

# 1. 因子精确公式计算
# Feature 1: RET (对数收益率) = ln(Close_t / Close_{t-1})
ret = np.zeros(len(close))
ret[1:] = np.log(close[1:] / close[:-1])

# Feature 2: VOL_CHG (成交量变动率) = (Vol_t - Vol_{t-1}) / Vol_{t-1}
vol_chg = np.zeros(len(volume))
vol_chg[1:] = (volume[1:] - volume[:-1]) / (volume[:-1] + 1e-6)

# Feature 3: HL_SPREAD (高低振幅) = (High - Low) / Close
hl_spread = (high - low) / (close + 1e-6)

# Feature 4: PRESSURE (买卖盘不平衡度) = (Close - Low) / (High - Low)
pressure = (close - low) / (high - low + 1e-6)

# 2. 涌现的强化学习 Q-State 价值算子 (时序差分 TD 递归)
# V(t) = gamma * V(t-1) + alpha * (ret * 15.0 + 0.2 * hl_spread)
gamma = 0.90
alpha = 0.10
q_state = np.zeros(len(close))
for t in range(1, len(close)):
    reward_est = ret[t] * 15.0 + 0.2 * hl_spread[t]
    q_state[t] = gamma * q_state[t-1] + alpha * reward_est

# 3. 统计偏离通道 (MA20 与 Z-Score)
def calc_sma(arr, window):
    s = pd.Series(arr)
    return s.rolling(window, min_periods=1).mean().values

def calc_std(arr, window):
    s = pd.Series(arr)
    return s.rolling(window, min_periods=1).std().replace(0, 1e-6).values

ma20 = calc_sma(close, 20)
std20 = calc_std(close, 20)
zscore = (close - ma20) / (std20 + 1e-6)

# RSI
deltas = np.diff(close, prepend=close[0])
gains = np.where(deltas > 0, deltas, 0)
losses = np.where(deltas < 0, -deltas, 0)
avg_gains = pd.Series(gains).rolling(14, min_periods=1).mean().values
avg_losses = pd.Series(losses).rolling(14, min_periods=1).mean().values
rs = avg_gains / (avg_losses + 1e-6)
rsi = 100 - (100 / (1 + rs))

# 4. 执行回测并收集完整日志
# 风控与执行规则：
# 止盈 0.9%，止损 2.5%，手续费单边 0.05%
tp_pct = 0.009
sl_pct = 0.025
fee_rate = 0.0005

position = 0
entry_price = 0.0
entry_idx = 0
cash = 10000.0
qty = 0.0
trades_log = []
all_events = []

for t in range(50, len(close)):
    dt = str(dates[t])
    cp = close[t]
    z = zscore[t]
    q = q_state[t]
    r = rsi[t]
    
    # 规则 1: 多头平仓/止盈止损判定
    if position == 1:
        pnl_pct = (cp - entry_price) / entry_price
        if pnl_pct >= tp_pct:
            net_pnl = qty * (cp - entry_price) - qty * cp * fee_rate
            cash += qty * cp - qty * cp * fee_rate
            log_item = {
                "timestamp": dt,
                "price": round(cp, 2),
                "action": "CLOSE_LONG (平多止盈)",
                "pnl": f"{net_pnl:+.2f} USDT",
                "pnl_pct": f"{pnl_pct*100:+.2f}%",
                "reason_rule": f"【规则-动态止盈】浮盈达到 +{pnl_pct*100:.2f}% (>= {tp_pct*100}%)，Q状态价值={q:.4f}，系统主动锁定利润平仓。"
            }
            trades_log.append(log_item)
            all_events.append(log_item)
            position = 0
            continue
        elif pnl_pct <= -sl_pct:
            net_pnl = qty * (cp - entry_price) - qty * cp * fee_rate
            cash += qty * cp - qty * cp * fee_rate
            log_item = {
                "timestamp": dt,
                "price": round(cp, 2),
                "action": "STOP_LOSS_LONG (平多止损)",
                "pnl": f"{net_pnl:+.2f} USDT",
                "pnl_pct": f"{pnl_pct*100:+.2f}%",
                "reason_rule": f"【规则-硬性止损】浮亏达到 {pnl_pct*100:.2f}% (<= -{sl_pct*100}%)，触发强行风控截断，立即市价平仓出局。"
            }
            trades_log.append(log_item)
            all_events.append(log_item)
            position = 0
            continue
        elif t - entry_idx >= 72: # 超时平仓风控 (保护持仓不超过 3 天)
            net_pnl = qty * (cp - entry_price) - qty * cp * fee_rate
            cash += qty * cp - qty * cp * fee_rate
            log_item = {
                "timestamp": dt,
                "price": round(cp, 2),
                "action": "TIMEOUT_EXIT_LONG (超时离场)",
                "pnl": f"{net_pnl:+.2f} USDT",
                "pnl_pct": f"{pnl_pct*100:+.2f}%",
                "reason_rule": f"【规则-时间止损】持仓已达 72 小时资金效率阈值，无论盈亏强制市价清仓。"
            }
            trades_log.append(log_item)
            all_events.append(log_item)
            position = 0
            continue

    # 规则 2: 空头平仓/止盈止损判定
    elif position == -1:
        pnl_pct = (entry_price - cp) / entry_price
        if pnl_pct >= tp_pct:
            net_pnl = qty * (entry_price - cp) - qty * cp * fee_rate
            cash += qty * (entry_price * 2 - cp) - qty * cp * fee_rate
            log_item = {
                "timestamp": dt,
                "price": round(cp, 2),
                "action": "CLOSE_SHORT (平空止盈)",
                "pnl": f"{net_pnl:+.2f} USDT",
                "pnl_pct": f"{pnl_pct*100:+.2f}%",
                "reason_rule": f"【规则-动态止盈】空头浮盈达到 +{pnl_pct*100:.2f}% (>= {tp_pct*100}%)，系统触发追踪止盈指令。"
            }
            trades_log.append(log_item)
            all_events.append(log_item)
            position = 0
            continue
        elif pnl_pct <= -sl_pct:
            net_pnl = qty * (entry_price - cp) - qty * cp * fee_rate
            cash += qty * (entry_price * 2 - cp) - qty * cp * fee_rate
            log_item = {
                "timestamp": dt,
                "price": round(cp, 2),
                "action": "STOP_LOSS_SHORT (平空止损)",
                "pnl": f"{net_pnl:+.2f} USDT",
                "pnl_pct": f"{pnl_pct*100:+.2f}%",
                "reason_rule": f"【规则-硬性止损】行情向上击穿止损线，空头浮亏 {pnl_pct*100:.2f}% (<= -{sl_pct*100}%)，触发强平止损保护。"
            }
            trades_log.append(log_item)
            all_events.append(log_item)
            position = 0
            continue
        elif t - entry_idx >= 72:
            net_pnl = qty * (entry_price - cp) - qty * cp * fee_rate
            cash += qty * (entry_price * 2 - cp) - qty * cp * fee_rate
            log_item = {
                "timestamp": dt,
                "price": round(cp, 2),
                "action": "TIMEOUT_EXIT_SHORT (超时离场)",
                "pnl": f"{net_pnl:+.2f} USDT",
                "pnl_pct": f"{pnl_pct*100:+.2f}%",
                "reason_rule": f"【规则-时间止损】空头持仓达 72 小时周期，盘整未达预期，强制平仓释放资金。"
            }
            trades_log.append(log_item)
            all_events.append(log_item)
            position = 0
            continue

    # 规则 3: 开仓入场判定
    if position == 0:
        # 多头入场条件：Z-Score 超卖 + Q-State 价值估值健康 + RSI 低位钝化
        if (z < -1.5) and (q > -0.01) and (r < 40):
            alloc = cash * 0.75
            qty = (alloc * (1 - fee_rate)) / cp
            cash -= alloc
            entry_price = cp
            entry_idx = t
            position = 1
            log_item = {
                "timestamp": dt,
                "price": round(cp, 2),
                "action": "ENTRY_LONG (开多/委托75%)",
                "pnl": "--",
                "pnl_pct": "--",
                "reason_rule": f"【规则-多头共振开仓】Z-Score={z:.2f}<-1.5(超跌突破布林下轨) 且 Q-State={q:.4f}>-0.01(状态价值积极，无暴跌预期) 且 RSI={r:.1f}<40(超卖)，触发开多信号。"
            }
            trades_log.append(log_item)
            all_events.append(log_item)
            
        # 空头入场条件：Z-Score 超买 + Q-State 价值估值阻力 + RSI 高位
        elif (z > 1.5) and (q < 0.01) and (r > 60):
            alloc = cash * 0.75
            qty = (alloc * (1 - fee_rate)) / cp
            cash -= alloc
            entry_price = cp
            entry_idx = t
            position = -1
            log_item = {
                "timestamp": dt,
                "price": round(cp, 2),
                "action": "ENTRY_SHORT (开空/委托75%)",
                "pnl": "--",
                "pnl_pct": "--",
                "reason_rule": f"【规则-空头共振开仓】Z-Score={z:.2f}>1.5(冲高突破布林上轨) 且 Q-State={q:.4f}<0.01(状态价值受阻) 且 RSI={r:.1f}>60(超买钝化)，触发做空信号。"
            }
            trades_log.append(log_item)
            all_events.append(log_item)
        else:
            # 记录少量典型观望
            if len(all_events) < 5 or t % 500 == 0:
                all_events.append({
                    "timestamp": dt,
                    "price": round(cp, 2),
                    "action": "HOLD (观望不动)",
                    "pnl": "--",
                    "pnl_pct": "--",
                    "reason_rule": f"【规则-通道内观望】当前 Z-Score={z:.2f} 处于 [-1.5, 1.5] 安全博弈区，RSI={r:.1f}，Q-State={q:.4f}，未达到极值触发条件，保持空仓观望。"
                })

# 统计总结果
exits = [t for t in trades_log if "CLOSE" in t["action"] or "STOP" in t["action"] or "TIMEOUT" in t["action"]]
wins = [t for t in exits if "+" in t["pnl_pct"]]
win_rate = (len(wins) / len(exits)) * 100 if len(exits) > 0 else 0

output_data = {
    "total_signals": len(trades_log),
    "completed_trades": len(exits),
    "winning_trades": len(wins),
    "losing_trades": len(exits) - len(wins),
    "win_rate": f"{win_rate:.2f}%",
    "trade_logs": trades_log,
    "event_samples": all_events[:25]
}

with open('/home/da/桌面/ethAI/strategy_engine/complete_trade_log.json', 'w', encoding='utf-8') as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

print(f"回测完成！总触发交易: {len(trades_log)}，已平仓: {len(exits)}，胜率: {win_rate:.2f}%")
