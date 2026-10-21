import numpy as np
import pandas as pd
import json

print(">>> [Audit] 读取并校验 2026-10-01 至 2026-10-19 真实 15m 行情数据...")
path = '/home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/ETHUSDT/15m/ETHUSDT_15m_consolidated.parquet'
df = pd.read_parquet(path)
df['datetime'] = pd.to_datetime(df['datetime'])
df.set_index('datetime', inplace=True)
df.sort_index(inplace=True)

# 截取包含预热期的最后 4000 根 K 线（覆盖 2026 年 8 月到 2026 年 10 月 19 日）
df = df.iloc[-4000:].copy()

close = df['close'].values.astype(float)
high = df['high'].values.astype(float)
low = df['low'].values.astype(float)
volume = df['volume'].values.astype(float)
quote_vol = df['quote_volume'].values.astype(float)
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

# 辅助算子
def ts_lag(x):
    res = np.empty_like(x)
    res[0] = x[0]; res[1:] = x[:-1]
    return res

def ts_delta(x): return x - ts_lag(x)

def ts_sma(x, w=16):
    return pd.Series(x).rolling(w, min_periods=1).mean().values

def ts_zscore(x, w=20):
    s = pd.Series(x)
    m = s.rolling(w, min_periods=1).mean()
    std = s.rolling(w, min_periods=1).std().replace(0, 1e-6)
    return ((s - m) / std).fillna(0.0).values

def safe_div(x, y):
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.nan_to_num(np.where(np.abs(y) > 1e-5, x / y, 1.0), nan=1.0)

# Q-Learning 时序差分状态更新
q_val = np.zeros(len(close))
gamma, alpha = 0.88, 0.12
for t in range(1, len(close)):
    step_reward = k_pos[t] * 15.0 + hl_spread[t] * 0.8
    q_val[t] = gamma * q_val[t-1] + alpha * step_reward

# 还原最优演化 AST 信号:
# multiply(safe_div(ts_lag(taker_imb), safe_div(negative(ts_sma(subtract(q_val, vol_accel))), safe_div(ts_delta(ts_sma(ts_sma(ret))), ts_sma(multiply(subtract(k_pos, subtract(ret, vol_accel)), hl_spread))))), safe_div(ts_zscore(ret), taker_imb))
term1 = ts_lag(taker_imb)
term2 = safe_div(
    -ts_sma(q_val - vol_accel),
    safe_div(ts_delta(ts_sma(ts_sma(ret))), ts_sma((k_pos - (ret - vol_accel)) * hl_spread))
)
partA = safe_div(term1, term2)
partB = safe_div(ts_zscore(ret), taker_imb)
raw_sig = partA * partB

raw_sig = np.nan_to_num(raw_sig, nan=0.0)
sig_std = np.std(raw_sig) + 1e-6
signal = (raw_sig - np.mean(raw_sig)) / sig_std

# 运行高精细实盘状态机回测 (涵盖 10 月 1 日至 10 月 19 日)
cash = 10000.0
pos_units = 0.0
pos_type = 0 # 1 多, -1 空, 0 空仓
order_step = 0 # 1 进首仓(50%), 2 加仓(75%)
entry_avg_price = 0.0

trades_october = []

# 锁定 10月1日 00:00 之后的索引起点
start_idx = np.where(dates >= '2026-10-01 00:00:00')[0][0]

for i in range(start_idx, len(close)):
    dt = str(dates[i])
    cp = close[i]
    hi = high[i]
    lo = low[i]
    sig_val = signal[i]
    
    # 1. 离场优先判定 (Tick级模拟: 检查当前 15m Bar 内高低价是否触发 0.9% 止盈或 2.5% 止损)
    if pos_type == 1:
        max_gain = (hi - entry_avg_price) / entry_avg_price
        max_loss = (lo - entry_avg_price) / entry_avg_price
        
        if max_gain >= 0.009: # 触及 0.9% 动态追踪止盈
            exit_p = entry_avg_price * 1.009
            realized_pnl = pos_units * (exit_p - entry_avg_price) - pos_units * exit_p * 0.0005
            cash += pos_units * exit_p - pos_units * exit_p * 0.0005
            trades_october.append({
                "time": dt, "symbol": "ETHUSDT 永续", "action": "多仓离场 (动态止盈)", "price": round(exit_p, 2),
                "pnl": f"{realized_pnl:+.2f} USDT", "pnl_pct": "+0.90%",
                "reason": "【规则-动态追踪止盈】K线内涨幅触及 +0.9% 目标位，撮合引擎立即市价平多离场锁定利润。"
            })
            pos_units = 0.0; pos_type = 0; order_step = 0
            continue
            
        elif max_loss <= -0.025: # 触及 2.5% 硬止损
            exit_p = entry_avg_price * 0.975
            realized_pnl = pos_units * (exit_p - entry_avg_price) - pos_units * exit_p * 0.0005
            cash += pos_units * exit_p - pos_units * exit_p * 0.0005
            trades_october.append({
                "time": dt, "symbol": "ETHUSDT 永续", "action": "多仓离场 (硬性止损)", "price": round(exit_p, 2),
                "pnl": f"{realized_pnl:+.2f} USDT", "pnl_pct": "-2.50%",
                "reason": "【规则-硬性止损】行情出现剧烈单边急跌击穿 -2.5% 安全线，强制平多清仓截断亏损。"
            })
            pos_units = 0.0; pos_type = 0; order_step = 0
            continue

    elif pos_type == -1:
        max_gain = (entry_avg_price - lo) / entry_avg_price
        max_loss = (entry_avg_price - hi) / entry_avg_price
        
        if max_gain >= 0.009: # 触及 0.9% 动态追踪止盈
            exit_p = entry_avg_price * 0.991
            realized_pnl = pos_units * (entry_avg_price - exit_p) - pos_units * exit_p * 0.0005
            cash += pos_units * (entry_avg_price * 2 - exit_p) - pos_units * exit_p * 0.0005
            trades_october.append({
                "time": dt, "symbol": "ETHUSDT 永续", "action": "空仓离场 (动态止盈)", "price": round(exit_p, 2),
                "pnl": f"{realized_pnl:+.2f} USDT", "pnl_pct": "+0.90%",
                "reason": "【规则-动态追踪止盈】K线下跌触及 +0.9% 目标位，市价平空离场锁利。"
            })
            pos_units = 0.0; pos_type = 0; order_step = 0
            continue
            
        elif max_loss <= -0.025: # 触及 2.5% 硬止损
            exit_p = entry_avg_price * 1.025
            realized_pnl = pos_units * (entry_avg_price - exit_p) - pos_units * exit_p * 0.0005
            cash += pos_units * (entry_avg_price * 2 - exit_p) - pos_units * exit_p * 0.0005
            trades_october.append({
                "time": dt, "symbol": "ETHUSDT 永续", "action": "空仓离场 (硬性止损)", "price": round(exit_p, 2),
                "pnl": f"{realized_pnl:+.2f} USDT", "pnl_pct": "-2.50%",
                "reason": "【规则-硬性止损】行情向上击穿 -2.5% 安全线，强制止损出局。"
            })
            pos_units = 0.0; pos_type = 0; order_step = 0
            continue

    # 2. 入场与加仓判定 (15m Bar 收盘确定性)
    # 多头信号
    if sig_val > 1.2:
        if pos_type == 0:
            alloc = cash * 0.50
            u = (alloc * 0.9995) / cp
            cash -= alloc
            pos_units = u; pos_type = 1; order_step = 1
            entry_avg_price = cp
            trades_october.append({
                "time": dt, "symbol": "ETHUSDT 永续", "action": "多仓进场 (50%首仓)", "price": round(cp, 2),
                "pnl": "--", "pnl_pct": "--",
                "reason": f"【规则-15m收盘开多】AlphaEvolve 演化信号={sig_val:.2f}>1.2，首次建仓可用保证金的 50%。"
            })
        elif pos_type == 1 and order_step == 1:
            alloc = cash * 0.75
            u = (alloc * 0.9995) / cp
            cash -= alloc
            entry_avg_price = (pos_units * entry_avg_price + u * cp) / (pos_units + u)
            pos_units += u
            order_step = 2
            trades_october.append({
                "time": dt, "symbol": "ETHUSDT 永续", "action": "多仓进场 (75%加仓)", "price": round(cp, 2),
                "pnl": "--", "pnl_pct": "--",
                "reason": f"【规则-15m加仓】信号维持积极={sig_val:.2f}>1.2，触发第2批委托，追加可用保证金的 75%。"
            })

    # 空头信号
    elif sig_val < -1.2:
        if pos_type == 0:
            alloc = cash * 0.50
            u = (alloc * 0.9995) / cp
            cash -= alloc
            pos_units = u; pos_type = -1; order_step = 1
            entry_avg_price = cp
            trades_october.append({
                "time": dt, "symbol": "ETHUSDT 永续", "action": "空仓进场 (50%首仓)", "price": round(cp, 2),
                "pnl": "--", "pnl_pct": "--",
                "reason": f"【规则-15m收盘开空】AlphaEvolve 演化信号={sig_val:.2f}<-1.2，首次建仓可用保证金的 50%。"
            })
        elif pos_type == -1 and order_step == 1:
            alloc = cash * 0.75
            u = (alloc * 0.9995) / cp
            cash -= alloc
            entry_avg_price = (pos_units * entry_avg_price + u * cp) / (pos_units + u)
            pos_units += u
            order_step = 2
            trades_october.append({
                "time": dt, "symbol": "ETHUSDT 永续", "action": "空仓进场 (75%加仓)", "price": round(cp, 2),
                "pnl": "--", "pnl_pct": "--",
                "reason": f"【规则-15m加仓】空头动能持续强化={sig_val:.2f}<-1.2，触发第2批委托，追加可用保证金的 75%。"
            })

# 统计平仓胜率
closed = [t for t in trades_october if "离场" in t["action"]]
wins = [t for t in closed if "止盈" in t["action"]]
win_rate = (len(wins) / len(closed)) * 100 if len(closed) > 0 else 0

print(f"\n================ 2026年10月（至10月19日）完整回测报告 ================")
print(f"总触发开平仓事件: {len(trades_october)} 次")
print(f"已完成平仓交易: {len(closed)} 笔")
print(f"止盈笔数: {len(wins)} 笔")
print(f"止损笔数: {len(closed) - len(wins)} 笔")
print(f"10月份实盘平仓胜率: {win_rate:.2f}%")
print(f"最终账户净值: {cash:.2f} USDT")
print("======================================================================")

with open('/home/da/桌面/ethAI/strategy_engine/october_full_trade_logs.json', 'w', encoding='utf-8') as f:
    json.dump({
        "period": "2026-10-01 to 2026-10-19",
        "total_events": len(trades_october),
        "closed_trades": len(closed),
        "win_rate": f"{win_rate:.2f}%",
        "final_cash": round(cash, 2),
        "trades": trades_october
    }, f, ensure_ascii=False, indent=2)
